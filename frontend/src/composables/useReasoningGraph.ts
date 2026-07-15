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
}

export function useReasoningGraph(graph: ComputedRef<ReasoningGraph | null>) {
  const flowNodes = computed<Node[]>(() => {
    if (!graph.value) return []

    const spacingY = 150  // 垂直间距
    const centerX = 300   // 水平居中
    const nodes: Node[] = []
    const activeNodes = graph.value.nodes.filter(n => n.status !== 'discarded')

    activeNodes.forEach((node, idx) => {
      const colorScheme = NODE_COLORS[node.type] || { bg: '#f0f0f0', border: '#d9d9d9', label: node.type }
      const isBranch = node.status === 'branch'

      nodes.push({
        id: node.id,
        position: { x: centerX - 100, y: idx * spacingY },  // 单列垂直，居中对齐
        data: {
          label: node.label,
          type: node.type,
          status: node.status,
          data: node.data,
          color: colorScheme,
          isBranch,
        },
        style: {
          background: isBranch ? '#f0e6ff' : colorScheme.bg,
          border: `2px solid ${isBranch ? '#b37feb' : colorScheme.border}`,
          borderRadius: '8px',
          padding: '12px',
          minWidth: '200px',
          opacity: isBranch ? 0.85 : 1,
          boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
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

      edges.push({
        id: `edge_${idx}`,
        source: edge.from,
        target: edge.to,
        animated: style.animated,
        style: {
          stroke: style.color,
          strokeWidth: 2,
          ...(style.dashed ? { strokeDasharray: '5,5' } : {}),
        },
        markerEnd: {
          width: 12,
          height: 12,
          orient: 'auto',
          refX: 6,
          refY: 6,
          color: style.color,
          type: 'arrowclosed',
        },
      })
    })

    return edges
  })

  return { flowNodes, flowEdges }
}
