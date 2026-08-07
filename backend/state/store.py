"""MindGlass 状态存储"""

from typing import Optional
from state.models import ReasoningNode, ReasoningEdge, BranchRecord, ReasoningMeta


class ReasoningGraphStore:
    """管理推理图状态：nodes + edges + branches"""

    def __init__(self):
        self.nodes: list[ReasoningNode] = []
        self.edges: list[ReasoningEdge] = []
        self.branches: list[BranchRecord] = []
        self.meta = ReasoningMeta()
        self._next_step_index = 0

    def add_node(self, node: ReasoningNode):
        self.nodes.append(node)
        self._next_step_index = node.step_index + 1
        self.meta.current_step_index = node.step_index
        self.meta.total_steps = self._next_step_index

    def add_edge(self, edge: ReasoningEdge):
        self.edges.append(edge)

    def get_node_by_id(self, node_id: str) -> Optional[ReasoningNode]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def get_node_by_index(self, step_index: int) -> Optional[ReasoningNode]:
        """获取指定 step_index 的节点（包括 discarded 和 branch）"""
        candidates = [n for n in self.nodes if n.step_index == step_index]
        # 优先返回非 discarded 的
        active = [n for n in candidates if n.status not in ("discarded",)]
        return active[0] if active else (candidates[-1] if candidates else None)

    def get_latest_node(self, node_type: Optional[str] = None) -> Optional[ReasoningNode]:
        """获取最新的指定类型的节点"""
        candidates = [n for n in self.nodes if n.status not in ("discarded",)]
        if node_type:
            candidates = [n for n in candidates if n.type == node_type]
        return max(candidates, key=lambda n: n.step_index) if candidates else None

    def truncate_from(self, step_index: int) -> list[str]:
        """从 step_index 开始截断（含该节点），标记为 branch 以保留历史。
        返回被截断的节点 id。"""
        discarded_ids = []
        for node in self.nodes:
            if node.step_index >= step_index and node.status not in ("branch",):
                node.status = "branch"
                discarded_ids.append(node.id)
        self.mark_branch_edges()
        return discarded_ids

    def mark_branch_edges(self) -> None:
        """任一端已废弃（branch/replaced/discarded）的边转成 Branch 展示边（虚线）。
        废弃链的展示边只"标记"不"删除"——打断时不知道哪些节点后续会被重试废弃，
        提前删边会导致废弃链断链；统一在状态标记完成后调用本方法收敛边类型。
        存活节点指向废弃评估的旧边同样先标虚线，等新 Observe 诞生时由重连逻辑移除。"""
        dead = ("branch", "replaced", "discarded")
        for edge in self.edges:
            src = self.get_node_by_id(edge.from_id)
            tgt = self.get_node_by_id(edge.to_id)
            if (src is not None and tgt is not None
                    and (src.status in dead or tgt.status in dead)):
                edge.type = "Branch"

    def create_branch(self, discarded_from: str, discarded_node_ids: list, reason: str = "") -> str:
        branch_id = f"branch_{len(self.branches) + 1}"
        self.branches.append(BranchRecord(branch_id, discarded_from, discarded_node_ids, reason))
        return branch_id

    def to_dict(self):
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "branches": [b.to_dict() for b in self.branches],
            "meta": self.meta.to_dict(),
        }

    def reset(self):
        self.nodes.clear()
        self.edges.clear()
        self.branches.clear()
        self.meta = ReasoningMeta()
        self._next_step_index = 0
