"""MindGlass Agent — 手写 ReAct 循环

核心逻辑：
1. Plan → 拆解步骤
2. 循环执行 ToolCall → Observe
3. 生成 Answer

每个步骤生成 Node 对象，通过 SSE 推送事件。
支持截断重放：从任意 ToolCall 节点截断，保留历史分支，重新执行后续所有步骤。
"""

import asyncio
import uuid
import json
from typing import AsyncGenerator, Optional
from datetime import datetime

from state.store import ReasoningGraphStore
from state.models import ReasoningNode, ReasoningEdge
from agent.planner import plan
from agent.tools import execute_tool
from agent.answerer import generate_answer

# 超时设置（秒）
TOOL_TIMEOUT = 120
LLM_TIMEOUT = 60


def _make_node_id(step_index: int, node_type: str) -> str:
    """生成全局唯一节点 ID：类型_stepIndex_uuid前缀"""
    return f"{node_type.lower()}_{step_index}_{uuid.uuid4().hex[:6]}"


class ReactLoop:
    """手写 ReAct 循环"""

    def __init__(self, store: ReasoningGraphStore):
        self.store = store
        self.run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.query = ""
        self.step_index = 0
        self._cached_steps: list[dict] = []
        self._cached_plan_info: str = ""

    def _emit(self, event_type: str, data: dict) -> str:
        """格式化 SSE 事件"""
        return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"

    def _prev_node_id(self) -> Optional[str]:
        """获取最新非 discarded、非 branch 节点的 ID（用于连边）"""
        for node in reversed(self.store.nodes):
            if node.status not in ("discarded", "branch"):
                return node.id
        return None

    def _add_edge(self, from_id: str, to_id: str, edge_type: str = "Normal") -> None:
        """添加边"""
        self.store.add_edge(ReasoningEdge(from_id=from_id, to_id=to_id, edge_type=edge_type))

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

    async def _run_steps(self, steps: list[dict], start_index: int, observations: list) -> AsyncGenerator[str, None]:
        """
        从 start_index 开始执行 steps 循环，包含 ToolCall → Observe。
        用于 run() 和 retry_from() 复用。
        """
        for i in range(start_index, len(steps)):
            step = steps[i]
            tool_name = step.get("tool", "search")
            tool_params = step.get("params", {})
            description = step.get("description", "")

            # 先获取上一个节点 ID（在 add_node 之前！）
            prev_id = self._prev_node_id()

            # ToolCall
            yield self._emit("status", {"message": f"🔧 正在执行: {tool_name}"})
            success, tool_result = await self._safe_tool_call(tool_name, tool_params)

            tc_node = ReasoningNode(
                node_id=_make_node_id(self.step_index, "ToolCall"),
                node_type="ToolCall",
                data={
                    "tool": tool_name,
                    "params": tool_params,
                    "result": tool_result,
                    "description": description,
                },
                status="done" if success else "error",
                step_index=self.step_index,
                label=f"{tool_name}",
            )
            self.store.add_node(tc_node)
            if prev_id:
                self._add_edge(prev_id, tc_node.id)
            yield self._emit("node_complete", {"node": tc_node.to_dict(), "graph": self.store.to_dict()})

            self.step_index += 1
            prev_id = tc_node.id  # 现在上一个节点是 ToolCall

            # Observe（即使工具失败也生成观察节点，方便调试）
            yield self._emit("status", {"message": "📡 收集结果..."})

            obs_node = ReasoningNode(
                node_id=_make_node_id(self.step_index, "Observe"),
                node_type="Observe",
                data={
                    "source": tc_node.id,
                    "tool": tool_name,
                    "result_summary": json.dumps(tool_result, ensure_ascii=False),
                },
                status="done",
                step_index=self.step_index,
                label="观察结果",
            )
            self.store.add_node(obs_node)
            self._add_edge(prev_id, obs_node.id)
            yield self._emit("node_complete", {"node": obs_node.to_dict(), "graph": self.store.to_dict()})

            observations.append(tool_result)
            self.step_index += 1

    async def _generate_answer(self, query: str, observations: list, plan_info: str = "") -> AsyncGenerator[str, None]:
        """生成最终回答"""
        yield self._emit("status", {"message": "✍️ 正在生成回答..."})

        # 传入完整上下文：query + 规划思路 + observations
        context = f"规划思路：{plan_info}" if plan_info else ""
        try:
            answer = await asyncio.wait_for(
                generate_answer(query, observations, context),
                timeout=LLM_TIMEOUT,
            )
        except asyncio.TimeoutError:
            answer = f"回答生成超时（{LLM_TIMEOUT}s），请重试。"

        # 先获取上一个节点 ID
        prev_id = self._prev_node_id()

        ans_node = ReasoningNode(
            node_id=_make_node_id(self.step_index, "Answer"),
            node_type="Answer",
            data={
                "input": query,
                "output": answer,
                "observations_count": len(observations),
            },
            status="done",
            step_index=self.step_index,
            label="最终回答",
        )
        self.store.add_node(ans_node)
        if prev_id:
            self._add_edge(prev_id, ans_node.id)

        yield self._emit("node_complete", {"node": ans_node.to_dict(), "graph": self.store.to_dict()})
        yield self._emit("run_complete", {"graph": self.store.to_dict()})

    async def run(self, query: str) -> AsyncGenerator[str, None]:
        """执行完整的 ReAct 循环"""
        self.query = query
        self.store.reset()
        self.store.meta.run_id = self.run_id
        self.store.meta.query = query

        # Step 0: Plan
        yield self._emit("status", {"message": "🤔 正在规划..."})
        plan_result = await plan(query)
        steps = plan_result.get("steps", [])
        plan_info = plan_result.get("thought", "")

        plan_node = ReasoningNode(
            node_id=_make_node_id(self.step_index, "Plan"),
            node_type="Plan",
            data={
                "input": query,
                "output": plan_info,
                "steps": steps,
            },
            status="done",
            step_index=self.step_index,
            label=f"规划 ({len(steps)} 步)",
        )
        self.store.add_node(plan_node)
        yield self._emit("node_complete", {"node": plan_node.to_dict(), "graph": self.store.to_dict()})

        self.step_index += 1

        # 保存 steps 到 meta，供 retry_from 复用
        self.store.meta.total_steps = len(steps)
        self._cached_steps = steps
        self._cached_plan_info = plan_info

        observations: list = []
        async for event in self._run_steps(steps, 0, observations):
            yield event

        async for event in self._generate_answer(query, observations, plan_info):
            yield event

    async def retry_from(self, step_index: int, edited_data: Optional[dict] = None) -> AsyncGenerator[str, None]:
        """
        从指定 step 截断并重试。
        支持编辑 ToolCall 的 params/tool 后，截断后续所有节点，用新数据重新执行。
        """
        yield self._emit("status", {"message": "🔄 截断中..."})

        # 1. 截断指定 step 及之后的节点
        discarded_ids = self.store.truncate_from(step_index)
        if discarded_ids:
            self.store.create_branch(
                discarded_from=f"step_{step_index}",
                discarded_node_ids=discarded_ids,
                reason="用户编辑后重试",
            )

        # 找到被截断处的节点（即要被编辑的节点）
        node = self.store.get_node_by_index(step_index)
        if not node:
            yield self._emit("error", {"message": f"未找到 step {step_index}"})
            return

        self.step_index = step_index

        # 2. 根据节点类型处理
        if node.type == "ToolCall":
            # 使用编辑后的数据（如果有），否则复用原节点的 params/tool
            effective_tool = node.data.get("tool", "search")
            effective_params = node.data.get("params", {})
            effective_description = node.data.get("description", "")

            if edited_data:
                if "params" in edited_data:
                    effective_params = edited_data["params"]
                if "tool" in edited_data:
                    effective_tool = edited_data["tool"]
                yield self._emit("status", {"message": f"📝 已更新参数: {json.dumps(effective_params, ensure_ascii=False)}"})

            # 收集截断前已有的 observations（完整结果）
            observations: list = []
            for n in self.store.nodes:
                if n.type == "Observe" and n.status == "done" and n.step_index < step_index:
                    source_id = n.data.get("source")
                    for tc in self.store.nodes:
                        if tc.type == "ToolCall" and tc.id == source_id and tc.status == "done":
                            observations.append(tc.data.get("result", {}))

            # 截断前最后一个活跃节点（step_index < step_index 的最后一个非 branch 节点）
            prev_id = None
            for n in reversed(self.store.nodes):
                if n.status not in ("discarded", "branch") and n.step_index < step_index:
                    prev_id = n.id
                    break

            yield self._emit("status", {"message": f"🔧 重新执行: {effective_tool}"})
            success, tool_result = await self._safe_tool_call(effective_tool, effective_params)

            tc_node = ReasoningNode(
                node_id=_make_node_id(self.step_index, "ToolCall"),
                node_type="ToolCall",
                data={
                    "tool": effective_tool,
                    "params": effective_params,
                    "result": tool_result,
                    "description": effective_description,
                },
                status="done" if success else "error",
                step_index=self.step_index,
                label=f"{effective_tool}（重试）",
            )
            self.store.add_node(tc_node)
            if prev_id:
                self._add_edge(prev_id, tc_node.id)
            yield self._emit("node_complete", {"node": tc_node.to_dict(), "graph": self.store.to_dict()})

            # 生成新的 Observe 节点
            self.step_index += 1
            prev_id = tc_node.id

            obs_node = ReasoningNode(
                node_id=_make_node_id(self.step_index, "Observe"),
                node_type="Observe",
                data={
                    "source": tc_node.id,
                    "tool": effective_tool,
                    "result_summary": json.dumps(tool_result, ensure_ascii=False),
                },
                status="done",
                step_index=self.step_index,
                label="观察结果",
            )
            self.store.add_node(obs_node)
            self._add_edge(prev_id, obs_node.id)
            yield self._emit("node_complete", {"node": obs_node.to_dict(), "graph": self.store.to_dict()})

            observations.append(tool_result)
            self.step_index += 1

            # 继续执行后续 steps（从当前 step 的下一个开始）
            # 推算在 steps 列表中的位置：step_index=1 对应 steps[0], step_index=3 对应 steps[1], ...
            current_tool_index = (step_index - 1) // 2
            remaining_steps = self._cached_steps[current_tool_index + 1:] if current_tool_index + 1 < len(self._cached_steps) else []

            if remaining_steps:
                async for event in self._run_steps(remaining_steps, 0, observations):
                    yield event
            else:
                yield self._emit("status", {"message": "✍️ 正在生成回答..."})

            # 生成最终回答
            async for event in self._generate_answer(self.query, observations, self._cached_plan_info):
                yield event

        elif node.type == "Plan":
            # Plan 编辑：更新规划思路，重新生成 steps
            if edited_data and "output" in edited_data:
                node.data["output"] = edited_data["output"]
                if "steps" in edited_data:
                    self._cached_steps = edited_data["steps"]
                    self.store.meta.total_steps = len(edited_data["steps"])
                    node.label = f"规划 ({len(edited_data['steps'])} 步)"
                node.status = "done"
                yield self._emit("node_complete", {"node": node.to_dict()})
                yield self._emit("status", {"message": "📝 已更新规划"})

            observations = []
            async for event in self._run_steps(self._cached_steps, 0, observations):
                yield event
            async for event in self._generate_answer(self.query, observations, self._cached_plan_info):
                yield event

        elif node.type == "Observe":
            # Observe 编辑：手动覆盖观察结果，继续后续步骤
            if edited_data and "result_summary" in edited_data:
                node.data["result_summary"] = edited_data["result_summary"]
                node.status = "done"
                yield self._emit("node_complete", {"node": node.to_dict()})

            # 从后续 ToolCall 继续
            current_tool_index = (step_index) // 2
            remaining_steps = self._cached_steps[current_tool_index:]

            observations = []
            for n in self.store.nodes:
                if n.type == "Observe" and n.status == "done" and n.step_index < step_index:
                    source_id = n.data.get("source")
                    for tc in self.store.nodes:
                        if tc.type == "ToolCall" and tc.id == source_id and tc.status == "done":
                            observations.append(tc.data.get("result", {}))

            if remaining_steps:
                async for event in self._run_steps(remaining_steps, 0, observations):
                    yield event
            async for event in self._generate_answer(self.query, observations, self._cached_plan_info):
                yield event

        else:
            yield self._emit("error", {"message": f"不支持重试 {node.type} 节点，请从 ToolCall 节点重试"})
            yield self._emit("run_complete", {"graph": self.store.to_dict()})
