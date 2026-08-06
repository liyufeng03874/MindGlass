"""MindGlass 数据模型"""

from enum import Enum
from typing import Optional


class NodeType(str, Enum):
    Plan = "Plan"
    ToolCall = "ToolCall"
    Observe = "Observe"
    Answer = "Answer"


class NodeStatus(str, Enum):
    Done = "done"
    Current = "current"
    Pending = "pending"
    Error = "error"
    Discarded = "discarded"
    Branch = "branch"


class EdgeType(str, Enum):
    Normal = "Normal"
    Retry = "Retry"
    Fallback = "Fallback"
    Branch = "Branch"


class ReasoningNode:
    """推理步骤节点"""
    def __init__(
        self,
        node_id: str,
        node_type: str,
        data: dict,
        status: str = "pending",
        step_index: int = 0,
        branch_id: Optional[str] = None,
        label: str = "",
        duration_ms: Optional[int] = None,
    ):
        self.id = node_id
        self.type = node_type
        self.data = data
        self.status = status
        self.step_index = step_index
        self.branch_id = branch_id
        self.label = label
        self.duration_ms = duration_ms  # 节点执行用时（毫秒）

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "type": self.type,
            "data": self.data,
            "status": self.status,
            "step_index": self.step_index,
            "branch_id": self.branch_id,
            "label": self.label,
        }
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        return result


class ReasoningEdge:
    """节点之间的边"""
    def __init__(self, from_id: str, to_id: str, edge_type: str = "Normal"):
        self.from_id = from_id
        self.to_id = to_id
        self.type = edge_type

    def to_dict(self) -> dict:
        return {
            "from": self.from_id,
            "to": self.to_id,
            "type": self.type,
        }


class BranchRecord:
    """被丢弃的历史分支"""
    def __init__(self, branch_id: str, discarded_from: str, discarded_node_ids: list, reason: str = ""):
        self.id = branch_id
        self.discarded_from = discarded_from
        self.discarded_node_ids = discarded_node_ids
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "discarded_from": self.discarded_from,
            "discarded_node_ids": self.discarded_node_ids,
            "reason": self.reason,
        }


class ReasoningMeta:
    """运行元信息"""
    def __init__(self, query: str = "", run_id: str = ""):
        self.current_step_index: int = 0
        self.total_steps: int = 0
        self.query = query
        self.run_id = run_id
        self.run_started_at: Optional[float] = None  # 本次运行开始时间（秒级时间戳）
        self.plan_count: int = 0  # 当前 Plan 轮次（v2 决策循环）
        self.interrupted: bool = False  # 本次 run 是否被用户打断

    def to_dict(self) -> dict:
        result = {
            "current_step_index": self.current_step_index,
            "total_steps": self.total_steps,
            "query": self.query,
            "run_id": self.run_id,
            "plan_count": self.plan_count,
            "interrupted": self.interrupted,
        }
        if self.run_started_at is not None:
            result["run_started_at"] = self.run_started_at
        return result
