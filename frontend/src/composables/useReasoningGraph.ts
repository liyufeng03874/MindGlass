import { computed, type ComputedRef } from 'vue'
import type { Node, Edge } from '@vue-flow/core'
import type { ReasoningGraph, AgentNode, AgentEdge, NodeStatus } from '@/types/agent'

// 节点类型 → 颜色映射
const NODE_COLORS: Record<string, { bg: string; border: string; label: string }> = {
  Plan:      { bg: '#e8f4fd', border: '#1677ff', label: '🧠 规划' },
  ToolCall:  { bg: '#f6ffed', border: '#52c41a', label: '🔧 执行' },
  Observe:   { bg: '#fff7e6', border: '#fa8c16', label: '📡 观察' },
  Answer:    { bg: '#f9f0ff', border: '#722ed1', label: '💬 回答' },
}

// 边类型 → 样式映射
const EDGE_STYLES: Record<string, { color: string; animated: boolean; dashed: boolean }> = {
  Normal:  { color: '#1677ff', animated: false, dashed: false },
  Retry:   { color: '#fa8c16', animated: true,  dashed: true },
  Fallback:{ color: '#ff4d4f', animated: true,  dashed: true },
  Branch:  { color: '#722ed1', animated: true,  dashed: true },
  Pending: { color: '#b0b0b0', animated: true,  dashed: true },
}

export function useReasoningGraph(graph: ComputedRef<ReasoningGraph | null>) {
  const flowNodes = computed<Node[]>(() => {
    if (!graph.value) return []

    const spacingY = 150  // 垂直间距（按 step_index）
    const centerX = 300   // 水平居中
    const branchOffsetX = -120  // branch 路径左偏移
    const newBranchOffsetX = 120  // 新路径右偏移
    const nodes: Node[] = []
    const activeNodes = graph.value.nodes.filter(n => n.status !== 'discarded')

    // 找到分叉点：第一个 branch 节点的 step_index
    const firstBranchStep = activeNodes.find(n => n.status === 'branch')?.step_index
    // 新路径的起点：第一个非 branch 但 step_index >= firstBranchStep 的节点
    const newBranchStartStep = firstBranchStep !== undefined
      ? activeNodes.find(n => n.status !== 'branch' && n.step_index >= firstBranchStep)?.step_index
      : undefined

    activeNodes.forEach((node) => {
      const colorScheme = NODE_COLORS[node.type] || { bg: '#f0f0f0', border: '#d9d9d9', label: node.type }
      const isBranch = node.status === 'branch'
      const isPending = node.status === 'pending'
      const isNewBranch = newBranchStartStep !== undefined && node.step_index >= newBranchStartStep && !isBranch

      // 分叉布局：branch 路径左偏，新路径右偏
      let xOffset = 0
      if (isBranch) xOffset = branchOffsetX
      else if (isNewBranch) xOffset = newBranchOffsetX

      nodes.push({
        id: node.id,
        position: { x: centerX - 100 + xOffset, y: node.step_index * spacingY },
        data: {
          label: node.label,
          type: node.type,
          status: node.status,
          data: node.data,
          color: colorScheme,
          isBranch,
        },
        style: {
          background: isPending ? '#fafafa' : (isBranch ? '#f5f5f5' : colorScheme.bg),
          border: `2px ${isPending ? 'dashed' : 'solid'} ${isPending ? '#d9d9d9' : (isBranch ? '#d9d9d9' : colorScheme.border)}`,
          borderRadius: '8px',
          padding: '12px',
          minWidth: '200px',
          opacity: isPending ? 0.4 : (isBranch ? 0.5 : 1),
          boxShadow: isPending ? 'none' : '0 2px 8px rgba(0,0,0,0.08)',
        },
      })
    })

    return nodes
  })

  const flowEdges = computed<Edge[]>(() => {
    if (!graph.value) return []

    const activeIds = new Set(graph.value.nodes.filter(n => n.status !== 'discarded').map(n => n.id))
    const edges: Edge[] = []

    graph.value.edges.forEach((edge, idx) => {
      if (!activeIds.has(edge.from) || !activeIds.has(edge.to)) return

      const style = EDGE_STYLES[edge.type] || EDGE_STYLES.Normal
      const isBranchEdge = edge.type === 'Branch'
      const isPendingEdge = edge.type === 'Pending'

      edges.push({
        id: `edge_${idx}`,
        source: edge.from,
        target: edge.to,
        animated: isBranchEdge ? false : style.animated,
        style: {
          stroke: isPendingEdge ? '#d9d9d9' : (isBranchEdge ? '#d9d9d9' : style.color),
          strokeWidth: isPendingEdge ? 1 : (isBranchEdge ? 1 : 2),
          ...(isPendingEdge ? { strokeDasharray: '6,4' } : (isBranchEdge ? { strokeDasharray: '4,4' } : (style.dashed ? { strokeDasharray: '5,5' } : {}))),
        },
        markerEnd: isPendingEdge
          ? undefined
          : (isBranchEdge
            ? undefined
            : {
                width: 12,
                height: 12,
                orient: 'auto',
                refX: 6,
                refY: 6,
                color: style.color,
                type: 'arrowclosed',
              }),
      })
    })

    return edges
  })

  return { flowNodes, flowEdges }
}
