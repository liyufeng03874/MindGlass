"""MindGlass Agent — 决策循环（v2）

核心架构变更：
- 旧：Plan → [ToolCall → Observe(搬运)]* → Answer
- 新：Plan(1) → [ToolCall → Observe(评估) → Plan(N)]* → Answer

Observe 节点做结构化评估（总结/去重/矛盾检测），Plan 节点做决策（sufficient/need_more/terminate）。
形成真正的 Reason-Act-Observe 决策回环，最多 3 轮。

设计文档：docs/observe-plan-design.md
"""

import asyncio
import uuid
import json
from typing import AsyncGenerator, Optional
from datetime import datetime
import time

from state.store import ReasoningGraphStore
from state.models import ReasoningNode, ReasoningEdge
from agent.planner import plan
from agent.observer import observe
from agent.tools import execute_tool
from agent.answerer import generate_answer

# 超时设置（秒）
TOOL_TIMEOUT = 120
LLM_TIMEOUT = 60
MAX_PLAN_COUNT = 3


def _make_node_id(step_index: int, node_type: str) -> str:
    """生成全局唯一节点 ID：类型_stepIndex_uuid前缀"""
    return f"{node_type.lower()}_{step_index}_{uuid.uuid4().hex[:6]}"


# 工具名 → 中文节点标签（前端图上显示）
TOOL_LABELS = {
    "search": "工具（网络搜索）",
    "rag_retrieve": "工具（RAG 检索）",
}


def _tool_label(tool_name: str) -> str:
    """将工具名映射为中文节点标签，未知工具兜底"""
    return TOOL_LABELS.get(tool_name, f"工具（{tool_name}）")


class ReactLoop:
    """决策循环（v2）：Plan-Observe 回环"""

    def __init__(self, store: ReasoningGraphStore):
        self.store = store
        self.run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.query = ""
        self.step_index = 0
        self._last_node: Optional[ReasoningNode] = None

    # ── 基础设施 ──

    def _emit(self, event_type: str, data: dict) -> str:
        """格式化 SSE 事件"""
        return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"

    def _prev_node_id(self) -> Optional[str]:
        """获取最新非 discarded、非 branch、非 replaced 节点的 ID（用于连边）"""
        for node in reversed(self.store.nodes):
            if node.status not in ("discarded", "branch", "replaced"):
                return node.id
        return None

    def _add_edge(self, from_id: str, to_id: str, edge_type: str = "Normal") -> None:
        """添加边"""
        self.store.add_edge(ReasoningEdge(from_id=from_id, to_id=to_id, edge_type=edge_type))

    def _mark_node_duration(self, node: ReasoningNode, start_time: float) -> None:
        """记录节点执行耗时（毫秒）"""
        node.duration_ms = round((time.time() - start_time) * 1000)

    def _emit_last_node(self) -> str:
        """发送最后一个节点的 SSE 事件"""
        node = self._last_node
        return self._emit("node_complete", {"node": node.to_dict(), "graph": self.store.to_dict()})

    async def _safe_tool_call(self, tool_name: str, params: dict) -> tuple[bool, dict]:
        """安全执行工具，返回 (success, result)"""
        try:
            result = await asyncio.wait_for(
                execute_tool(tool_name, params),
                timeout=TOOL_TIMEOUT,
            )
            return True, result
        except asyncio.TimeoutError:
            return False, {"error": f"工具 {tool_name} 执行超时（{TOOL_TIMEOUT}s）"}
        except Exception as e:
            return False, {"error": f"工具执行失败: {str(e)}"}

    # ── 节点创建 ──

    def _create_plan_node(self, plan_result: dict, plan_count: int, start_time: float) -> ReasoningNode:
        """创建 Plan 节点"""
        decision = plan_result.get("decision", "need_more")
        steps = plan_result.get("steps", [])
        reasoning = plan_result.get("reasoning", plan_result.get("thought", ""))

        # 标签根据决策类型变化
        # 首次规划不再显示步数：v2 回环中后续可能补搜，步数无法预料
        if plan_count == 1:
            label = "规划"
        elif decision == "sufficient":
            label = f"决策：信息充足"
        elif decision == "need_more":
            label = f"决策：需要补搜"
        elif decision == "terminate":
            label = f"决策：强制终止"
        else:
            label = f"决策 ({decision})"

        node = ReasoningNode(
            node_id=_make_node_id(self.step_index, "Plan"),
            node_type="Plan",
            data={
                "input": self.query,
                "output": reasoning,
                "steps": steps,
                "decision": decision,
                "reasoning": reasoning,
                "plan_count": plan_count,
                "if_need_more": plan_result.get("if_need_more"),
                "if_terminate": plan_result.get("if_terminate"),
            },
            status="done",
            step_index=self.step_index,
            label=label,
        )
        self._mark_node_duration(node, start_time)
        self._last_node = node
        return node

    def _commit_plan_node(self, plan_node: ReasoningNode) -> None:
        """将 Plan 节点加入 store，并从前一个有效节点（通常是 Observe）连边。
        首个 Plan 节点无前驱，不连边。"""
        prev_id = self._prev_node_id()
        self.store.add_node(plan_node)
        if prev_id:
            self._add_edge(prev_id, plan_node.id)

    def _create_toolcall_node(self, step: dict, success: bool, result: dict,
                              parallel_group_id: Optional[str] = None,
                              start_time: Optional[float] = None) -> ReasoningNode:
        """创建 ToolCall 节点"""
        tool_name = step.get("tool", "search")
        node = ReasoningNode(
            node_id=_make_node_id(self.step_index, "ToolCall"),
            node_type="ToolCall",
            data={
                "tool": tool_name,
                "params": step.get("params", {}),
                "result": result,
                "description": step.get("description", ""),
                "parallel_group_id": parallel_group_id,
            },
            status="done" if success else "error",
            step_index=self.step_index,
            label=_tool_label(tool_name),
        )
        if start_time is not None:
            self._mark_node_duration(node, start_time)
        return node

    def _create_observe_node(self, obs_output: dict, source_ids: list[str],
                             parallel_group_id: Optional[str] = None,
                             start_time: Optional[float] = None) -> ReasoningNode:
        """创建 Observe 节点（结构化评估）"""
        node = ReasoningNode(
            node_id=_make_node_id(self.step_index, "Observe"),
            node_type="Observe",
            data={
                "source": source_ids,
                "observe_output": obs_output,
                "summary": obs_output.get("summary", ""),
                "key_findings": obs_output.get("key_findings", []),
                "conflicts": obs_output.get("conflicts", []),
                "duplicates_removed": obs_output.get("duplicates_removed", 0),
                "round": obs_output.get("round", 1),
            },
            status="done",
            step_index=self.step_index,
            label=f"评估（第{obs_output.get('round', '?')}轮）",
        )
        if start_time is not None:
            self._mark_node_duration(node, start_time)
        return node

    def _create_answer_node(self, query: str, answer: str, observe_count: int,
                            degraded: bool, start_time: float) -> ReasoningNode:
        """创建 Answer 节点"""
        label = "最终回答" if not degraded else "最终回答（信息可能不完整）"
        node = ReasoningNode(
            node_id=_make_node_id(self.step_index, "Answer"),
            node_type="Answer",
            data={
                "input": query,
                "output": answer,
                "observations_count": observe_count,
                "degraded": degraded,
            },
            status="done",
            step_index=self.step_index,
            label=label,
        )
        self._mark_node_duration(node, start_time)
        return node

    # ── 工具执行 ──

    async def _execute_tools(self, steps: list[dict]) -> AsyncGenerator[str, None]:
        """
        执行工具步骤（支持并行），创建 ToolCall 节点并推送 SSE。
        原始结果存储在 self._last_raw_results 中供后续 Observe 使用。
        """
        self._last_raw_results = []
        self._last_tc_node_ids = []

        if not steps:
            return

        # 所有步骤并行执行
        parallel_group_id = f"pg_{uuid.uuid4().hex[:6]}"
        parallel_prev_id = self._prev_node_id()

        if len(steps) > 1:
            yield self._emit("status", {"message": f"🔧 并行执行 {len(steps)} 个工具调用..."})
        else:
            yield self._emit("status", {"message": f"🔧 正在执行: {steps[0].get('tool', 'search')}"})

        batch_start = time.time()

        async def _exec(s):
            tn = s.get("tool", "search")
            tp = s.get("params", {})
            ok, res = await self._safe_tool_call(tn, tp)
            return s, ok, res

        results = await asyncio.gather(*[_exec(s) for s in steps])

        # 按原始顺序创建节点
        for s, ok, res in results:
            tc_node = self._create_toolcall_node(
                s, ok, res,
                parallel_group_id=parallel_group_id if len(steps) > 1 else None,
                start_time=batch_start,
            )
            self.store.add_node(tc_node)
            if parallel_prev_id:
                edge_type = "Parallel" if len(steps) > 1 else "Normal"
                self._add_edge(parallel_prev_id, tc_node.id, edge_type=edge_type)
            self._last_node = tc_node
            self._last_raw_results.append(res)
            self._last_tc_node_ids.append(tc_node.id)
            yield self._emit_last_node()

    async def _emit_observe(self, observe_outputs: list[dict]) -> AsyncGenerator[str, None]:
        """
        创建 Observe 节点：调用 LLM 做结构化评估。
        将评估结果追加到 observe_outputs 数组。
        """
        yield self._emit("status", {"message": "🔍 正在评估检索结果..."})
        obs_start = time.time()

        # 调用 LLM 做结构化评估
        try:
            obs_output = await asyncio.wait_for(
                observe(self.query, self._last_raw_results, observe_outputs),
                timeout=LLM_TIMEOUT,
            )
        except asyncio.TimeoutError:
            # 超时兜底：用原始结果生成简单摘要
            obs_output = {
                "round": len(observe_outputs) + 1,
                "summary": "评估超时，原始结果已保留",
                "key_findings": [],
                "conflicts": [],
                "duplicates_removed": 0,
                "new_info_vs_previous": "评估超时",
            }

        observe_outputs.append(obs_output)

        # 创建 Observe 节点
        obs_node = self._create_observe_node(
            obs_output,
            source_ids=list(self._last_tc_node_ids),
            start_time=obs_start,
        )
        self.store.add_node(obs_node)

        # 所有 ToolCall → Observe
        for tc_id in self._last_tc_node_ids:
            self._add_edge(tc_id, obs_node.id)

        self._last_node = obs_node
        yield self._emit_last_node()

    # ── 回答生成 ──

    async def _generate_answer(self, observe_outputs: list[dict],
                               plan_decision: dict, degraded: bool) -> AsyncGenerator[str, None]:
        """生成最终回答"""
        if degraded:
            yield self._emit("status", {"message": "✍️ 正在生成回答（信息可能不完整）..."})
        else:
            yield self._emit("status", {"message": "✍️ 正在生成回答..."})

        answer_start = time.time()

        try:
            answer = await asyncio.wait_for(
                generate_answer(self.query, observe_outputs, plan_decision, degraded),
                timeout=LLM_TIMEOUT,
            )
        except asyncio.TimeoutError:
            answer = f"回答生成超时（{LLM_TIMEOUT}s），请重试。"

        prev_id = self._prev_node_id()
        ans_node = self._create_answer_node(
            self.query, answer, len(observe_outputs), degraded, answer_start,
        )
        self.store.add_node(ans_node)
        if prev_id:
            self._add_edge(prev_id, ans_node.id)
        self._last_node = ans_node

        yield self._emit_last_node()

        # 日志
        graph_summary = {
            "nodes": [
                {"id": n.id, "type": n.type, "step_index": n.step_index,
                 "label": n.label, "status": n.status,
                 "decision": n.data.get("decision") if n.data else None}
                for n in self.store.nodes
            ],
            "edges": [
                {"from": e.from_id, "to": e.to_id, "type": e.type}
                for e in self.store.edges
            ],
        }
        print(f"\n{'='*60}")
        print(f"[Run Complete] graph_summary: {json.dumps(graph_summary, ensure_ascii=False, indent=2)}")
        print(f"{'='*60}\n")

        yield self._emit("run_complete", {"graph": self.store.to_dict()})

    # ── 主循环 ──

    async def run(self, query: str) -> AsyncGenerator[str, None]:
        """
        执行决策循环（v2）：
        Plan(1) → [ToolCall → Observe → Plan(N)]* → Answer
        最多 MAX_PLAN_COUNT 轮 Plan。
        """
        self.query = query
        self.store.reset()
        self.store.meta.run_id = self.run_id
        self.store.meta.query = query
        self.store.meta.run_started_at = time.time()

        plan_count = 0
        observe_outputs: list[dict] = []

        # ── Plan(1)：首次规划 ──
        yield self._emit("status", {"message": "🤔 正在规划..."})
        plan_start = time.time()
        plan_result = await plan(query, observe_outputs=[], plan_count=1)
        plan_count = 1

        plan_node = self._create_plan_node(plan_result, plan_count, plan_start)
        self._commit_plan_node(plan_node)
        yield self._emit_last_node()
        self.step_index += 1

        # 保存 meta
        self.store.meta.total_steps = len(plan_result.get("steps", []))
        self.store.meta.plan_count = plan_count

        # ── 决策回环 ──
        while plan_result.get("decision") == "need_more" and plan_count < MAX_PLAN_COUNT:
            # 获取工具步骤
            if plan_count == 1:
                steps = plan_result.get("steps", [])
            else:
                # 补搜：将 suggested_queries 转为 steps
                suggested = plan_result.get("if_need_more", {})
                queries = suggested.get("suggested_queries", [])
                if not queries:
                    # LLM 说 need_more 但没给 query，兜底用原始 query
                    queries = [query]
                steps = [{"tool": "search", "description": q, "params": {"query": q}} for q in queries]

            # 执行工具
            async for event in self._execute_tools(steps):
                yield event
            self.step_index += 1

            # Observe：结构化评估
            async for event in self._emit_observe(observe_outputs):
                yield event
            self.step_index += 1

            # 重新规划（决策）
            plan_count += 1
            yield self._emit("status", {"message": f"🤔 第 {plan_count} 轮决策..."})
            plan_start = time.time()
            plan_result = await plan(query, observe_outputs, plan_count)

            plan_node = self._create_plan_node(plan_result, plan_count, plan_start)
            self._commit_plan_node(plan_node)
            yield self._emit_last_node()
            self.step_index += 1

            # 更新 meta
            self.store.meta.plan_count = plan_count

        # ── 终止 → Answer ──
        degraded = plan_result.get("decision") == "terminate"
        async for event in self._generate_answer(observe_outputs, plan_result, degraded):
            yield event

    # ── 截断重放 ──

    async def retry_from(self, step_index: int, edited_data: Optional[dict] = None) -> AsyncGenerator[str, None]:
        """
        从指定 step 截断并重试（v2 适配）。
        支持编辑 ToolCall 的 params/tool 后，截断后续所有节点，用新数据重新执行。
        """
        yield self._emit("status", {"message": "🔄 截断中..."})

        # 1. 截断
        discarded_ids = self.store.truncate_from(step_index)
        if discarded_ids:
            self.store.create_branch(
                discarded_from=f"step_{step_index}",
                discarded_node_ids=discarded_ids,
                reason="用户编辑后重试",
            )

        node = self.store.get_node_by_index(step_index)
        if not node:
            yield self._emit("error", {"message": f"未找到 step {step_index}"})
            return

        self.step_index = step_index

        # 收集截断前的 observe_outputs
        observe_outputs = self._collect_observe_outputs_before(step_index)

        if node.type == "ToolCall":
            effective_tool = node.data.get("tool", "search")
            effective_params = node.data.get("params", {})
            effective_description = node.data.get("description", "")

            if edited_data:
                if "params" in edited_data:
                    effective_params = edited_data["params"]
                if "tool" in edited_data:
                    effective_tool = edited_data["tool"]
                yield self._emit("status", {"message": f"📝 已更新参数: {json.dumps(effective_params, ensure_ascii=False)}"})

            # 重新执行工具
            yield self._emit("status", {"message": f"🔧 重新执行: {effective_tool}"})
            retry_start = time.time()
            success, tool_result = await self._safe_tool_call(effective_tool, effective_params)

            tc_node = self._create_toolcall_node(
                {"tool": effective_tool, "params": effective_params, "description": effective_description},
                success, tool_result, start_time=retry_start,
            )
            tc_node.label = f"{_tool_label(effective_tool)}（重试）"
            self.store.add_node(tc_node)
            prev_id = self._find_prev_before(step_index)
            if prev_id:
                self._add_edge(prev_id, tc_node.id)
            self._last_node = tc_node
            yield self._emit_last_node()

            # Observe
            self._last_raw_results = [tool_result]
            self._last_tc_node_ids = [tc_node.id]
            self.step_index += 1
            async for event in self._emit_observe(observe_outputs):
                yield event
            self.step_index += 1

            # 重新决策
            plan_count = (self.store.meta.plan_count or 1) + 1
            if plan_count > MAX_PLAN_COUNT:
                plan_count = MAX_PLAN_COUNT

            yield self._emit("status", {"message": f"🤔 第 {plan_count} 轮决策..."})
            plan_start = time.time()
            plan_result = await plan(self.query, observe_outputs, plan_count)

            plan_node = self._create_plan_node(plan_result, plan_count, plan_start)
            self._commit_plan_node(plan_node)
            yield self._emit_last_node()
            self.step_index += 1
            self.store.meta.plan_count = plan_count

            # 根据决策继续
            if plan_result.get("decision") == "need_more" and plan_count < MAX_PLAN_COUNT:
                suggested = plan_result.get("if_need_more", {})
                queries = suggested.get("suggested_queries", [self.query])
                steps = [{"tool": "search", "description": q, "params": {"query": q}} for q in queries]
                async for event in self._execute_tools(steps):
                    yield event
                self.step_index += 1
                async for event in self._emit_observe(observe_outputs):
                    yield event
                self.step_index += 1

                # 再次决策
                plan_count += 1
                plan_result = await plan(self.query, observe_outputs, plan_count)
                plan_node = self._create_plan_node(plan_result, plan_count, time.time())
                self._commit_plan_node(plan_node)
                yield self._emit_last_node()
                self.step_index += 1

            degraded = plan_result.get("decision") == "terminate"
            async for event in self._generate_answer(observe_outputs, plan_result, degraded):
                yield event

        elif node.type == "Plan":
            if edited_data and "output" in edited_data:
                node.data["output"] = edited_data["output"]
                if "steps" in edited_data:
                    node.data["steps"] = edited_data["steps"]
                node.status = "done"
                yield self._emit("node_complete", {"node": node.to_dict()})
                yield self._emit("status", {"message": "📝 已更新规划"})

            # 重新执行后续
            steps = node.data.get("steps", [])
            if steps:
                async for event in self._execute_tools(steps):
                    yield event
                self.step_index += 1
                async for event in self._emit_observe(observe_outputs):
                    yield event
                self.step_index += 1

            plan_count = 2
            plan_result = await plan(self.query, observe_outputs, plan_count)
            plan_node = self._create_plan_node(plan_result, plan_count, time.time())
            self._commit_plan_node(plan_node)
            yield self._emit_last_node()
            self.step_index += 1

            degraded = plan_result.get("decision") == "terminate"
            async for event in self._generate_answer(observe_outputs, plan_result, degraded):
                yield event

        elif node.type == "Observe":
            if edited_data and "observe_output" in edited_data:
                node.data["observe_output"] = edited_data["observe_output"]
                node.data["summary"] = edited_data["observe_output"].get("summary", "")
                node.data["key_findings"] = edited_data["observe_output"].get("key_findings", [])
                node.status = "done"
                yield self._emit("node_complete", {"node": node.to_dict()})

            # 从 Observe 之后重新决策
            plan_count = (self.store.meta.plan_count or 1) + 1
            if plan_count > MAX_PLAN_COUNT:
                plan_count = MAX_PLAN_COUNT

            plan_result = await plan(self.query, observe_outputs, plan_count)
            plan_node = self._create_plan_node(plan_result, plan_count, time.time())
            self._commit_plan_node(plan_node)
            yield self._emit_last_node()
            self.step_index += 1

            degraded = plan_result.get("decision") == "terminate"
            async for event in self._generate_answer(observe_outputs, plan_result, degraded):
                yield event

        else:
            yield self._emit("error", {"message": f"不支持重试 {node.type} 节点"})
            yield self._emit("run_complete", {"graph": self.store.to_dict()})

    async def retry_from_graph(self, step_index: int, old_nodes: list[dict],
                               new_nodes: list[dict], query: str,
                               plan_info: str) -> AsyncGenerator[str, None]:
        """
        方案 C：并行重试——前端发被编辑的旧节点+新节点，后端融合。
        v2 适配：Observe 使用结构化评估。
        """
        # ── 1. 旧节点标记 branch ──
        branch_ids = set()
        for node_data in old_nodes:
            existing = self.store.get_node_by_id(node_data["id"])
            if existing:
                existing.status = "branch"
                existing.data["branch"] = True
                existing.label = f"{node_data.get('label', node_data['type'])}（废弃）"
                branch_ids.add(existing.id)
                yield self._emit("node_complete", {"node": existing.to_dict(), "graph": self.store.to_dict()})

        # ── 2. 级联标记 replaced ──
        replaced_ids = set()
        to_visit = list(branch_ids)
        while to_visit:
            current_id = to_visit.pop(0)
            for edge in self.store.edges:
                if edge.from_id == current_id:
                    target = self.store.get_node_by_id(edge.to_id)
                    if target and target.status not in ("branch", "replaced"):
                        target.status = "replaced"
                        target.data["replaced"] = True
                        # Plan/Observe/Answer 级联废弃时统一追加（废弃）后缀
                        if target.type in ("Plan", "Observe", "Answer"):
                            target.label = f"{target.label or target.type}（废弃）"
                        replaced_ids.add(target.id)
                        yield self._emit("node_complete", {"node": target.to_dict(), "graph": self.store.to_dict()})
                        to_visit.append(target.id)

        # ── 3. 收集截断前的 observe_outputs ──
        observe_outputs = self._collect_observe_outputs_before(step_index)

        # ── 4. 执行新节点 ──
        self.step_index = step_index
        prev_id = self._find_prev_before(step_index)

        self._last_raw_results = []
        self._last_tc_node_ids = []

        for node_data in new_nodes:
            tool_name = node_data.get("data", {}).get("tool", "search")
            params = node_data.get("data", {}).get("params", {})

            yield self._emit("status", {"message": f"🔧 重新执行: {tool_name}"})
            retry_start = time.time()
            success, tool_result = await self._safe_tool_call(tool_name, params)

            tc_data = {
                "tool": tool_name,
                "params": params,
                "result": tool_result,
                "description": node_data.get("data", {}).get("description", ""),
            }
            if "parallel_group_id" in node_data.get("data", {}):
                tc_data["parallel_group_id"] = node_data["data"]["parallel_group_id"]

            tc_node = ReasoningNode(
                node_id=_make_node_id(self.step_index, "ToolCall"),
                node_type="ToolCall",
                data=tc_data,
                status="done" if success else "error",
                step_index=self.step_index,
                label=f"{_tool_label(tool_name)}（重试）",
            )
            self._mark_node_duration(tc_node, retry_start)
            self.store.add_node(tc_node)
            if prev_id:
                # 重试节点属于并行组时用 Parallel 边，与存活兄弟节点的绿色保持一致
                edge_type = "Parallel" if tc_node.data.get("parallel_group_id") else "Normal"
                self._add_edge(prev_id, tc_node.id, edge_type=edge_type)
            self._last_node = tc_node
            yield self._emit_last_node()

            self._last_raw_results.append(tool_result)
            self._last_tc_node_ids.append(tc_node.id)

        # ── 4.5 将同并行组中未被废弃的兄弟 ToolCall 纳入 Observe ──
        # 找到被编辑节点的 parallel_group_id
        sibling_pg_id = None
        for node_data in old_nodes:
            existing = self.store.get_node_by_id(node_data["id"])
            if existing and existing.data.get("parallel_group_id"):
                sibling_pg_id = existing.data["parallel_group_id"]
                break

        if sibling_pg_id:
            for n in self.store.nodes:
                if (n.type == "ToolCall"
                        and n.status == "done"
                        and n.data.get("parallel_group_id") == sibling_pg_id
                        and n.id not in self._last_tc_node_ids):
                    self._last_tc_node_ids.append(n.id)
                    self._last_raw_results.append(n.data.get("result", {}))

        # ── 5. Observe（结构化评估）──
        self.step_index += 1
        async for event in self._emit_observe(observe_outputs):
            yield event
        self.step_index += 1

        # ── 6. 决策 ──
        plan_count = (self.store.meta.plan_count or 1) + 1
        if plan_count > MAX_PLAN_COUNT:
            plan_count = MAX_PLAN_COUNT

        yield self._emit("status", {"message": f"🤔 第 {plan_count} 轮决策..."})
        plan_start = time.time()
        plan_result = await plan(query, observe_outputs, plan_count)

        plan_node = self._create_plan_node(plan_result, plan_count, plan_start)
        self._commit_plan_node(plan_node)
        yield self._emit_last_node()
        self.step_index += 1
        self.store.meta.plan_count = plan_count

        # ── 7. 根据决策继续或终止 ──
        if plan_result.get("decision") == "need_more" and plan_count < MAX_PLAN_COUNT:
            suggested = plan_result.get("if_need_more", {})
            queries = suggested.get("suggested_queries", [query])
            steps = [{"tool": "search", "description": q, "params": {"query": q}} for q in queries]
            async for event in self._execute_tools(steps):
                yield event
            self.step_index += 1
            async for event in self._emit_observe(observe_outputs):
                yield event
            self.step_index += 1

            plan_count += 1
            plan_result = await plan(query, observe_outputs, plan_count)
            plan_node = self._create_plan_node(plan_result, plan_count, time.time())
            self._commit_plan_node(plan_node)
            yield self._emit_last_node()
            self.step_index += 1

        degraded = plan_result.get("decision") == "terminate"
        async for event in self._generate_answer(observe_outputs, plan_result, degraded):
            yield event

    # ── 辅助方法 ──

    def _collect_observe_outputs_before(self, step_index: int) -> list[dict]:
        """收集指定 step_index 之前所有有效 Observe 节点的结构化输出"""
        outputs = []
        for n in self.store.nodes:
            if (n.type == "Observe"
                    and n.status in ("done",)
                    and n.step_index < step_index
                    and n.data.get("observe_output")):
                outputs.append(n.data["observe_output"])
        return outputs

    def _find_prev_before(self, step_index: int) -> Optional[str]:
        """找到指定 step_index 之前最后一个有效节点"""
        for n in reversed(self.store.nodes):
            if n.status not in ("discarded", "branch", "replaced") and n.step_index < step_index:
                return n.id
        return None
