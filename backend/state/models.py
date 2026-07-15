"""MindGlass 数据模型"""

from typing import Optional, Literal

# 节点类型
NodeType = Literal["Plan", "ToolCall", "Observe", "Answer"]
NodeStatus = Literal["done", "current", "pending", "error", "discarded", "branch"]
EdgeType = Literal["Normal", "Retry", "Fallback", "Branch"]


class NodeData:
    """节点数据 payload"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}


class ReasoningNode:
    """推理步骤节点"""
    def __init__(
        self,
        node_id: str,
        node_type: NodeType,
        data: dict,
        status: NodeStatus = "pending",
        step_index: int = 0,
        branch_id: Optional[str] = None,
        label: str = "",
    ):
        self.id = node_id
        self.type = node_type
        self.data = data
        self.status = status
        self.step_index = step_index
        self.branch_id = branch_id
        self.label = label

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "data": self.data,
            "status": self.status,
            "step_index": self.step_index,
            "branch_id": self.branch_id,
            "label": self.label,
        }


class ReasoningEdge:
    """节点之间的边"""
    def __init__(self, from_id: str, to_id: str, edge_type: EdgeType = "Normal"):
        self.from_id = from_id
        self.to_id = to_id
        self.type = edge_type

    def to_dict(self):
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

    def to_dict(self):
        return {
            "id": self.id,
            "discarded_from": self.discarded_from,
            "discarded_node_ids": self.discarded_node_ids,
            "reason": self.reason,
        }


class ReasoningMeta:
    """运行元信息"""
    def __init__(self, query: str = "", run_id: str = ""):
        self.current_step_index = 0
        self.total_steps = 0
        self.query = query
        self.run_id = run_id

    def to_dict(self):
        return {
            "current_step_index": self.current_step_index,
            "total_steps": self.total_steps,
            "query": self.query,
            "run_id": self.run_id,
        }
