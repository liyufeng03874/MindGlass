"""MindGlass Agent — 决策循环（v2）

核心架构变更：
- 旧：Plan → [ToolCall → Observe(搬运)]* → Answer
- 新：Plan(1) → [ToolCall → Observe(评估) → Plan(N)]* → Answer

Observe 节点做结构化评估（总结/去重/矛盾检测），Plan 节点做决策（sufficient/need_more/terminate）。
形成真正的 Reason-Act-Observe 决策回环，最多 3 轮。

v2.2 新增：流式推送（node_streaming 事件），左侧思考直播。
设计文档：docs/observe-plan-design.md
"""

import asyncio
import uuid
import json
import queue as _queue
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

    # ── 流式 LLM 调用（线程池 + Queue） ──

    async def _stream_llm(self, node_id: str, node_type: str, messages: list, timeout: int = LLM_TIMEOUT) -> AsyncGenerator[str, None]:
        """
        通用流式 LLM 调用：在线程池中执行同步流式请求，
        通过 Queue 把 chunk 跨线程传递给 async generator，
        边收边 emit node_streaming 事件。

        node_streaming 事件格式：
        {
            "node_id": str,
            "node_type": "Plan"|"Observe"|"Answer",
            "chunk": str(本次增量文本),
            "content": str(累计全文),
            "is_complete": bool
        }
        """
        from agent.llm import LLM_MODEL
        from agent.llm import client

        q: _queue.Queue = _queue.Queue()
        full_text = ""

        def _run_stream():
            """在线程中执行流式 LLM 调用，把 chunk 放入队列"""
            try:
                stream = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=2048,
                    stream=True,
                )
                ft = ""
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        token = chunk.choices[0].delta.content
                        ft += token
                        q.put(("chunk", token, ft))
                q.put(("done", "", ft))
            except Exception as e:
                q.put(("error", str(e), ""))

        # 在线程池中启动，不阻塞事件循环
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _run_stream)

        # 消费队列，yield SSE 事件（带超时保护）
        try:
            while True:
                try:
                    tag, chunk_text, content = q.get_nowait()
                except _queue.Empty:
                    # 队列空，等待一下再试
                    await asyncio.sleep(0.05)
                    continue

                if tag == "error":
                    yield self._emit("node_streaming", {
                        "node_id": node_id,
                        "node_type": node_type,
                        "chunk": f"[流式调用出错: {chunk_text}]",
                        "content": full_text,
                        "is_complete": True,
                    })
                    return

                if tag == "chunk":
                    yield self._emit("node_streaming", {
                        "node_id": node_id,
                        "node_type": node_type,
                        "chunk": chunk_text,
                        "content": content,
                        "is_complete": False,
                    })
                    full_text = content
                elif tag == "done":
                    yield self._emit("node_streaming", {
                        "node_id": node_id,
                        "node_type": node_type,
                        "chunk": "",
                        "content": content,
                        "is_complete": True,
                    })
                    full_text = content
                    break

            # 等待线程完成（清理）
            try:
                await asyncio.wait_for(future, timeout=5)
            except asyncio.TimeoutError:
                pass
        except asyncio.TimeoutError:
            yield self._emit("node_streaming", {
                "node_id": node_id,
                "node_type": node_type,
                "chunk": f"[LLM 流式调用超时（{timeout}s）]",
                "content": full_text,
                "is_complete": True,
            })

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
        self._last_node = node
        return node

    # ── 流式 Plan 环节 ──

    async def _stream_plan(self, plan_count: int, observe_outputs: list[dict]) -> AsyncGenerator[str, None]:
        """
        流式 Plan 环节：
        1. 创建 Plan 节点（status="current"）
        2. 流式调用 LLM，边收 chunk 边 emit node_streaming
        3. 解析 JSON 结果
        4. 创建最终 Plan 节点（status="done"），emit node_complete
        """
        from agent.llm import LLM_MODEL
        from agent.llm import client
        from agent.planner import PLANNING_SYSTEM_PROMPT, DECISION_SYSTEM_PROMPT

        plan_node_id = _make_node_id(self.step_index, "Plan")
        plan_start = time.time()

        # 构建 prompt
        if plan_count == 1:
            prompt = f"用户查询: {self.query}\n\n请拆解为可执行步骤："
            messages = [
                {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        else:
            parts = [f"用户原始问题：{self.query}\n"]
            parts.append(f"当前是第 {plan_count} 轮规划（最多 3 轮）。\n")
            parts.append("=== 各轮检索评估报告 ===")
            for obs in observe_outputs:
                round_num = obs.get("round", "?")
                parts.append(f"\n--- 第 {round_num} 轮 ---")
                parts.append(f"摘要：{obs.get('summary', '')}")
                findings = obs.get("key_findings", [])
                if findings:
                    parts.append(f"要点：")
                    for f in findings:
                        parts.append(f"  - {f}")
                conflicts = obs.get("conflicts", [])
                if conflicts:
                    parts.append(f"矛盾：")
                    for c in conflicts:
                        parts.append(f"  - {c.get('topic', '')}: {c.get('resolution', '')} (置信度: {c.get('confidence', '?')})")
                new_info = obs.get("new_info_vs_previous", "")
                if new_info:
                    parts.append(f"新增信息：{new_info}")

            if plan_count >= 3:
                parts.append("\n⚠️ 这是第 3 轮（最后一轮）。如果信息仍然不足，你必须选择 terminate，在 partial_answer_note 中诚实说明哪些方面信息不完整。")
            parts.append("\n请判断信息是否足以回答用户问题，按 JSON 格式输出决策。")

            prompt = "\n".join(parts)
            messages = [
                {"role": "system", "content": DECISION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

        # 流式调用 LLM
        full_text = ""
        async for event in self._stream_llm(plan_node_id, "Plan", messages):
            yield event
            # 提取 is_complete=True 时的 content
            if '"is_complete": true' in event:
                parsed_event = json.loads(event.split("\n")[0].replace("data: ", ""))
                full_text = parsed_event["data"]["content"]

        # 解析 JSON
        if plan_count == 1:
            plan_result = self._parse_plan_result(full_text, self.query)
        else:
            plan_result = self._parse_decision_result(full_text, plan_count)

        # 创建最终 Plan 节点
        plan_node = self._create_plan_node(plan_result, plan_count, plan_start)
        self._commit_plan_node(plan_node)
        yield self._emit_last_node()

    def _parse_plan_result(self, text: str, query: str) -> dict:
        """解析首次规划的 JSON 结果"""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(cleaned)
            parsed["decision"] = "need_more"
            parsed["plan_count"] = 1
            return parsed
        except Exception:
            return {
                "thought": "无法解析规划结果，使用默认搜索策略",
                "steps": [
                    {"tool": "search", "description": "搜索相关信息", "params": {"query": query}}
                ],
                "decision": "need_more",
                "plan_count": 1,
            }

    def _parse_decision_result(self, text: str, plan_count: int) -> dict:
        """解析决策判断的 JSON 结果"""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(cleaned)
            parsed["plan_count"] = plan_count

            # 第 3 轮强制：如果 LLM 仍然返回 need_more，覆盖为 terminate
            if plan_count >= 3 and parsed.get("decision") == "need_more":
                parsed["decision"] = "terminate"
                parsed["reasoning"] = "已达最大检索轮次（3轮），强制终止"
                parsed["if_terminate"] = {
                    "reason": "已达最大检索轮次",
                    "partial_answer_note": parsed.get("if_need_more", {}).get("missing_aspects", ["部分信息"])[0] + "方面信息可能不完整",
                }
            return parsed
        except Exception:
            if plan_count >= 3:
                return {
                    "decision": "terminate",
                    "reasoning": "决策解析失败，已达最大轮次，强制终止",
                    "if_terminate": {
                        "reason": "决策解析失败",
                        "partial_answer_note": "回答生成过程中出现异常，部分信息可能不完整",
                    },
                    "plan_count": plan_count,
                }
            return {
                "decision": "sufficient",
                "reasoning": "决策解析失败，基于已有信息生成回答",
                "plan_count": plan_count,
            }

    # ── 流式 Observe 环节 ──

    async def _stream_observe(self, observe_outputs: list[dict]) -> AsyncGenerator[str, None]:
        """
        流式 Observe 环节：
        1. 创建 Observe 节点（status="current"）
        2. 流式调用 LLM，边收 chunk 边 emit node_streaming
        3. 解析 JSON 结果
        4. 创建最终 Observe 节点（status="done"），emit node_complete
        """
        from agent.llm import LLM_MODEL
        from agent.llm import client
        from agent.observer import OBSERVE_SYSTEM_PROMPT

        yield self._emit("status", {"message": "🔍 正在评估检索结果..."})
        obs_node_id = _make_node_id(self.step_index, "Observe")
        obs_start = time.time()

        # 构建 prompt
        parts = [f"用户原始问题：{self.query}\n"]
        previous_outputs = observe_outputs
        if previous_outputs:
            parts.append("=== 之前轮次的评估结果 ===")
            for i, prev in enumerate(previous_outputs):
                parts.append(f"\n--- 第 {prev.get('round', i + 1)} 轮 ---")
                parts.append(f"摘要：{prev.get('summary', '')}")
                findings = prev.get('key_findings', [])
                if findings:
                    parts.append(f"要点：{'; '.join(findings)}")
            parts.append("\n=== 本轮新检索结果 ===")

        for i, result in enumerate(self._last_raw_results):
            parts.append(f"\n--- 工具结果 {i + 1} ---")
            if isinstance(result, dict):
                if "error" in result:
                    parts.append(f"错误: {result['error']}")
                else:
                    parts.append(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                parts.append(str(result))

        round_num = len(previous_outputs) + 1
        parts.append(f"\n\n这是第 {round_num} 轮检索。请按 JSON 格式输出结构化评估（round 字段填 {round_num}）。")

        prompt = "\n".join(parts)
        messages = [
            {"role": "system", "content": OBSERVE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        # 流式调用 LLM
        full_text = ""
        try:
            async for event in self._stream_llm(obs_node_id, "Observe", messages):
                yield event
                if '"is_complete": true' in event:
                    parsed_event = json.loads(event.split("\n")[0].replace("data: ", ""))
                    full_text = parsed_event["data"]["content"]
        except Exception as e:
            # 超时或其他异常，用原始结果生成简单摘要
            full_text = None

        # 解析 JSON
        if full_text:
            try:
                cleaned = full_text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                obs_output = json.loads(cleaned)
                obs_output["round"] = round_num
            except Exception:
                obs_output = {
                    "round": round_num,
                    "summary": "评估结果解析失败，原始结果已保留",
                    "key_findings": [],
                    "conflicts": [],
                    "duplicates_removed": 0,
                    "new_info_vs_previous": "首轮检索" if round_num == 1 else "解析失败",
                }
        else:
            obs_output = {
                "round": round_num,
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

    # ── 流式 Answer 环节 ──

    async def _stream_answer(self, observe_outputs: list[dict],
                             plan_decision: dict, degraded: bool) -> AsyncGenerator[str, None]:
        """
        流式 Answer 环节：
        1. 创建 Answer 节点（status="current"）
        2. 流式调用 LLM，边收 chunk 边 emit node_streaming
        3. 创建最终 Answer 节点（status="done"），emit node_complete
        """
        from agent.llm import LLM_MODEL
        from agent.llm import client
        from agent.answerer import ANSWER_SYSTEM_PROMPT, ANSWER_DEGRADED_PREFIX

        if degraded:
            yield self._emit("status", {"message": "✍️ 正在生成回答（信息可能不完整）..."})
        else:
            yield self._emit("status", {"message": "✍️ 正在生成回答..."})

        answer_node_id = _make_node_id(self.step_index, "Answer")
        answer_start = time.time()

        # 构建上下文
        context_parts = []
        for obs in observe_outputs:
            round_num = obs.get("round", "?")
            context_parts.append(f"## 第 {round_num} 轮检索评估")
            context_parts.append(f"摘要：{obs.get('summary', '')}")
            findings = obs.get("key_findings", [])
            if findings:
                context_parts.append("要点：")
                for f in findings:
                    context_parts.append(f"  - {f}")
            conflicts = obs.get("conflicts", [])
            if conflicts:
                context_parts.append("矛盾处理：")
                for c in conflicts:
                    context_parts.append(f"  - {c.get('topic', '')}: {c.get('resolution', '')} (置信度: {c.get('confidence', '?')})")
            new_info = obs.get("new_info_vs_previous", "")
            if new_info and round_num != 1:
                context_parts.append(f"新增信息：{new_info}")

        if plan_decision:
            reasoning = plan_decision.get("reasoning", "")
            if reasoning:
                context_parts.append(f"\n## 决策说明\n{reasoning}")

        context = "\n\n".join(context_parts)
        prompt = f"""用户问题: {self.query}

收集到的结构化评估报告:
{context}

请根据以上评估报告回答用户的问题："""

        messages = [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        # 流式调用 LLM
        full_text = ""
        try:
            async for event in self._stream_llm(answer_node_id, "Answer", messages):
                yield event
                if '"is_complete": true' in event:
                    parsed_event = json.loads(event.split("\n")[0].replace("data: ", ""))
                    full_text = parsed_event["data"]["content"]
        except Exception:
            full_text = f"回答生成超时（{LLM_TIMEOUT}s），请重试。"

        # 降级模式：在回答前加提示信息
        if degraded and plan_decision:
            note = plan_decision.get("if_terminate", {}).get(
                "partial_answer_note",
                "部分信息可能不完整，建议进一步查证。"
            )
            full_text = ANSWER_DEGRADED_PREFIX.format(note=note) + full_text

        # 创建 Answer 节点
        prev_id = self._prev_node_id()
        ans_node = self._create_answer_node(
            self.query, full_text, len(observe_outputs), degraded, answer_start,
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

    # ── 工具执行 ──

    async def _execute_tools(self, steps: list[dict]) -> AsyncGenerator[str, None]:
        """
        执行工具步骤（支持并行），创建 ToolCall 节点并推送 SSE。
        原始结果存储在 self._last_raw_results 中供后续 Observe 使用。
        补强 node_complete 事件：带上 tool_name、params、result_preview。
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

            # 补强 node_complete 事件：带 tool_name、params、result_preview
            tool_name = s.get("tool", "search")
            params = s.get("params", {})
            # 结果预览：截断 500 字
            if isinstance(res, dict):
                result_preview = json.dumps(res, ensure_ascii=False)[:500]
            else:
                result_preview = str(res)[:500]

            yield self._emit("node_complete", {
                "node": tc_node.to_dict(),
                "graph": self.store.to_dict(),
                # 新增：前端左侧展示用
                "tool_name": tool_name,
                "params": params,
                "result_preview": result_preview,
            })

    # ── 主循环 ──

    async def run(self, query: str) -> AsyncGenerator[str, None]:
        """
        执行决策循环（v2）：
        Plan(1) → [ToolCall → Observe → Plan(N)]* → Answer
        最多 MAX_PLAN_COUNT 轮 Plan。

        v2.2：Plan/Observe/Answer 全部使用流式推送（node_streaming 事件）。
        """
        self.query = query
        self.store.reset()
        self.store.meta.run_id = self.run_id
        self.store.meta.query = query
        self.store.meta.run_started_at = time.time()

        plan_count = 0
        observe_outputs: list[dict] = []

        # ── Plan(1)：首次规划（流式） ──
        yield self._emit("status", {"message": "🤔 正在规划..."})
        async for event in self._stream_plan(1, []):
            yield event
        plan_count = 1

        # 获取最后一次 Plan 节点
        last_plan = None
        for node in reversed(self.store.nodes):
            if node.type == "Plan":
                last_plan = node
                break

        if last_plan:
            self.store.meta.total_steps = len(last_plan.data.get("steps", []))
            self.store.meta.plan_count = plan_count
            plan_result = last_plan.data

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

            # Observe：结构化评估（流式）
            async for event in self._stream_observe(observe_outputs):
                yield event
            self.step_index += 1

            # 重新规划（决策）（流式）
            plan_count += 1
            yield self._emit("status", {"message": f"🤔 第 {plan_count} 轮决策..."})
            async for event in self._stream_plan(plan_count, observe_outputs):
                yield event
            self.step_index += 1

            # 获取最新 Plan 节点更新 plan_result
            for node in reversed(self.store.nodes):
                if node.type == "Plan":
                    plan_result = node.data
                    break

            # 更新 meta
            self.store.meta.plan_count = plan_count

        # ── 终止 → Answer（流式） ──
        degraded = plan_result.get("decision") == "terminate"
        async for event in self._stream_answer(observe_outputs, plan_result, degraded):
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

            # Observe（流式）
            self._last_raw_results = [tool_result]
            self._last_tc_node_ids = [tc_node.id]
            self.step_index += 1
            async for event in self._stream_observe(observe_outputs):
                yield event
            self.step_index += 1

            # 重新决策（流式）
            plan_count = (self.store.meta.plan_count or 1) + 1
            if plan_count > MAX_PLAN_COUNT:
                plan_count = MAX_PLAN_COUNT

            yield self._emit("status", {"message": f"🤔 第 {plan_count} 轮决策..."})
            async for event in self._stream_plan(plan_count, observe_outputs):
                yield event
            self.step_index += 1
            self.store.meta.plan_count = plan_count

            # 获取最新 plan_result
            for n in reversed(self.store.nodes):
                if n.type == "Plan":
                    plan_result = n.data
                    break

            # 根据决策继续
            if plan_result.get("decision") == "need_more" and plan_count < MAX_PLAN_COUNT:
                suggested = plan_result.get("if_need_more", {})
                queries = suggested.get("suggested_queries", [self.query])
                steps = [{"tool": "search", "description": q, "params": {"query": q}} for q in queries]
                async for event in self._execute_tools(steps):
                    yield event
                self.step_index += 1
                async for event in self._stream_observe(observe_outputs):
                    yield event
                self.step_index += 1

                # 再次决策（流式）
                plan_count += 1
                async for event in self._stream_plan(plan_count, observe_outputs):
                    yield event
                self.step_index += 1

            degraded = plan_result.get("decision") == "terminate"
            for n in reversed(self.store.nodes):
                if n.type == "Plan":
                    plan_result = n.data
                    break
            async for event in self._stream_answer(observe_outputs, plan_result, degraded):
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
                async for event in self._stream_observe(observe_outputs):
                    yield event
                self.step_index += 1

            plan_count = 2
            async for event in self._stream_plan(plan_count, observe_outputs):
                yield event
            self.step_index += 1

            for n in reversed(self.store.nodes):
                if n.type == "Plan":
                    plan_result = n.data
                    break
            degraded = plan_result.get("decision") == "terminate"
            async for event in self._stream_answer(observe_outputs, plan_result, degraded):
                yield event

        elif node.type == "Observe":
            if edited_data and "observe_output" in edited_data:
                node.data["observe_output"] = edited_data["observe_output"]
                node.data["summary"] = edited_data["observe_output"].get("summary", "")
                node.data["key_findings"] = edited_data["observe_output"].get("key_findings", [])
                node.status = "done"
                yield self._emit("node_complete", {"node": node.to_dict()})

            # 从 Observe 之后重新决策（流式）
            plan_count = (self.store.meta.plan_count or 1) + 1
            if plan_count > MAX_PLAN_COUNT:
                plan_count = MAX_PLAN_COUNT

            async for event in self._stream_plan(plan_count, observe_outputs):
                yield event
            self.step_index += 1

            for n in reversed(self.store.nodes):
                if n.type == "Plan":
                    plan_result = n.data
                    break
            degraded = plan_result.get("decision") == "terminate"
            async for event in self._stream_answer(observe_outputs, plan_result, degraded):
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
                self._add_edge(prev_id, tc_node.id)
            self._last_node = tc_node
            yield self._emit_last_node()

            self._last_raw_results.append(tool_result)
            self._last_tc_node_ids.append(tc_node.id)

        # ── 5. Observe（流式） ──
        self.step_index += 1
        async for event in self._stream_observe(observe_outputs):
            yield event
        self.step_index += 1

        # ── 6. 重新决策（流式） ──
        plan_count = (self.store.meta.plan_count or 1) + 1
        if plan_count > MAX_PLAN_COUNT:
            plan_count = MAX_PLAN_COUNT

        yield self._emit("status", {"message": f"🤔 第 {plan_count} 轮决策..."})
        async for event in self._stream_plan(plan_count, observe_outputs):
            yield event
        self.step_index += 1

        for n in reversed(self.store.nodes):
            if n.type == "Plan":
                plan_result = n.data
                break
        degraded = plan_result.get("decision") == "terminate"
        async for event in self._stream_answer(observe_outputs, plan_result, degraded):
            yield event

    # ── 辅助 ──

    def _collect_observe_outputs_before(self, step_index: int) -> list[dict]:
        """收集 step_index 之前所有 Observe 节点的输出"""
        outputs = []
        for node in self.store.nodes:
            if node.type == "Observe" and node.step_index < step_index:
                if "observe_output" in node.data:
                    outputs.append(node.data["observe_output"])
        return outputs

    def _find_prev_before(self, step_index: int) -> Optional[str]:
        """查找 step_index 之前最后一个非废弃节点的 ID"""
        for node in reversed(self.store.nodes):
            if node.step_index < step_index and node.status not in ("discarded", "branch", "replaced"):
                return node.id
        return None
