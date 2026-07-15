"""MindGlass Agent — 手写 ReAct 循环

核心逻辑：
1. Plan → 拆解步骤
2. 循环执行 ToolCall → Observe
3. 生成 Answer

每个步骤生成 Node 对象，通过 SSE 推送事件。
支持截断重放：从任意 step 截断，保留历史分支。
"""

import uuid
import json
from typing import AsyncGenerator, Optional
from datetime import datetime

from state.store import ReasoningGraphStore
from state.models import ReasoningNode, ReasoningEdge
from agent.planner import plan
from agent.tools import execute_tool, list_tools
from agent.answerer import generate_answer


def _make_node_id(step_index: int, node_type: str) -> str:
    return f"{node_type.lower()}_{step_index}"


class ReactLoop:
    """手写 ReAct 循环"""

    def __init__(self, store: ReasoningGraphStore):
        self.store = store
        self.run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.query = ""
        self.step_index = 0

    def _emit(self, event_type: str, data: dict) -> str:
        """格式化 SSE 事件"""
        return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"

    async def run(self, query: str) -> AsyncGenerator[str, None]:
        """执行完整的 ReAct 循环，通过 SSE 推送事件"""
        self.query = query
        self.store.reset()
        self.store.meta.run_id = self.run_id
        self.store.meta.query = query

        # Step 0: Plan
        yield self._emit("status", {"message": "🤔 正在规划..."})
        plan_result = await plan(query)

        plan_node = ReasoningNode(
            node_id=_make_node_id(self.step_index, "Plan"),
            node_type="Plan",
            data={
                "input": query,
                "output": plan_result.get("thought", ""),
                "steps": plan_result.get("steps", []),
            },
            status="done",
            step_index=self.step_index,
            label=f"规划 ({len(plan_result.get('steps', []))} 步)",
        )
        self.store.add_node(plan_node)
        yield self._emit("node_complete", {"node": plan_node.to_dict()})

        self.step_index += 1

        # 循环执行步骤
        steps = plan_result.get("steps", [])
        observations = []

        for i, step in enumerate(steps):
            tool_name = step.get("tool", "search")
            tool_params = step.get("params", {})
            description = step.get("description", "")

            # ToolCall
            yield self._emit("status", {"message": f"🔧 正在执行: {tool_name}"})

            tool_result = await execute_tool(tool_name, tool_params)

            tc_node = ReasoningNode(
                node_id=_make_node_id(self.step_index, "ToolCall"),
                node_type="ToolCall",
                data={
                    "tool": tool_name,
                    "params": tool_params,
                    "result": tool_result,
                    "description": description,
                },
                status="done",
                step_index=self.step_index,
                label=f"{tool_name}",
            )
            self.store.add_node(tc_node)
            yield self._emit("node_complete", {"node": tc_node.to_dict()})

            # 添加边
            self.store.add_edge(ReasoningEdge(
                from_id=_make_node_id(self.step_index - 1 if self.step_index > 0 else 0,
                                      "Plan" if self.step_index == 1 else "ToolCall"),
                to_id=tc_node.id,
                edge_type="Normal",
            ))

            self.step_index += 1

            # Observe
            yield self._emit("status", {"message": "📡 收集结果..."})

            obs_node = ReasoningNode(
                node_id=_make_node_id(self.step_index, "Observe"),
                node_type="Observe",
                data={
                    "source": tc_node.id,
                    "tool": tool_name,
                    "result_summary": str(tool_result)[:200] if isinstance(tool_result, dict) else str(tool_result)[:200],
                },
                status="done",
                step_index=self.step_index,
                label="观察结果",
            )
            self.store.add_node(obs_node)
            yield self._emit("node_complete", {"node": obs_node.to_dict()})

            # 添加边
            self.store.add_edge(ReasoningEdge(
                from_id=tc_node.id,
                to_id=obs_node.id,
                edge_type="Normal",
            ))

            observations.append(tool_result)
            self.step_index += 1

        # 生成最终回答
        yield self._emit("status", {"message": "✍️ 正在生成回答..."})
        answer = await generate_answer(query, observations)

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

        # 添加最后一条边
        last_obs = self.store.get_latest_node("Observe")
        if last_obs:
            self.store.add_edge(ReasoningEdge(
                from_id=last_obs.id,
                to_id=ans_node.id,
                edge_type="Normal",
            ))

        yield self._emit("node_complete", {"node": ans_node.to_dict()})
        yield self._emit("run_complete", {"graph": self.store.to_dict()})

    async def retry_from(self, step_index: int, edited_data: Optional[dict] = None) -> AsyncGenerator[str, None]:
        """从指定 step 截断并重试"""
        # 截断
        discarded_ids = self.store.truncate_from(step_index)
        if discarded_ids:
            branch_id = self.store.create_branch(
                discarded_from=f"step_{step_index}",
                discarded_node_ids=discarded_ids,
                reason="用户修改后重试",
            )
        else:
            branch_id = None

        self.step_index = step_index

        # 找到被编辑节点之前的最后一个节点，用来连边
        prev_node = None
        for node in reversed(self.store.nodes):
            if node.step_index < step_index and node.status != "discarded":
                prev_node = node
                break

        # 重新执行
        node = self.store.get_node_by_index(step_index)
        if not node:
            yield self._emit("error", {"message": f"未找到 step {step_index}"})
            return

        if node.type == "ToolCall":
            # 如果是编辑后的，用新参数
            params = edited_data.get("params", node.data.get("params", {})) if edited_data else node.data.get("params", {})
            tool_name = edited_data.get("tool", node.data.get("tool", "search")) if edited_data else node.data.get("tool", "search")

            yield self._emit("status", {"message": f"🔧 正在重试: {tool_name}"})
            tool_result = await execute_tool(tool_name, params)

            # 创建新节点（分支）
            new_node = ReasoningNode(
                node_id=f"{node.type.lower()}_{step_index}_v2",
                node_type="ToolCall",
                data={
                    "tool": tool_name,
                    "params": params,
                    "result": tool_result,
                    "description": f"重试 (原: step_{step_index})",
                },
                status="branch",
                step_index=step_index,
                label=f"{tool_name} (重试)",
            )
            self.store.add_node(new_node)

            if prev_node:
                self.store.add_edge(ReasoningEdge(
                    from_id=prev_node.id,
                    to_id=new_node.id,
                    edge_type="Branch",
                ))

            yield self._emit("node_complete", {"node": new_node.to_dict()})
            yield self._emit("run_complete", {"graph": self.store.to_dict()})

        elif node.type == "Plan":
            yield self._emit("error", {"message": "Plan 节点重试暂不支持"})
            yield self._emit("run_complete", {"graph": self.store.to_dict()})

        else:
            yield self._emit("error", {"message": f"不支持重试 {node.type} 节点"})
            yield self._emit("run_complete", {"graph": self.store.to_dict()})
