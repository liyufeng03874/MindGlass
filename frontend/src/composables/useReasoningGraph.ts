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
  Parallel:{ color: '#52c41a', animated: false, dashed: false },
  Pending: { color: '#fa8c16', animated: true,  dashed: true },
}

export function useReasoningGraph(graph: ComputedRef<ReasoningGraph | null>) {
  const flowNodes = computed<Node[]>(() => {
    if (!graph.value) return []

    // console.log('[flowNodes] graph.nodes count:', graph.value.nodes.length)
    // console.log('[flowNodes] pending nodes:', graph.value.nodes.filter(n => n.status === 'pending').map(n => n.id))

    const spacingY = 150  // 垂直间距（按 step_index）
    const centerX = 300   // 水平居中
    const branchOffsetX = -120  // branch 路径左偏移
    const newBranchOffsetX = 120  // 新路径右偏移
    const spacingX = 220  // 并行节点水平间距
    const nodes: Node[] = []
    const activeNodes = graph.value.nodes.filter(n => n.status !== 'discarded')

    // 找到分叉点
    const firstBranchStep = activeNodes.find(n => n.status === 'branch')?.step_index

    // 检测并行组：同 step_index + 同 parallel_group_id 的 ToolCall 节点
    const parallelGroups = new Map<string, AgentNode[]>()
    activeNodes.forEach(node => {
      const pgId = node.data?.parallel_group_id
      if (pgId) {
        if (!parallelGroups.has(pgId)) parallelGroups.set(pgId, [])
        parallelGroups.get(pgId)!.push(node)
      }
    })

    // 记录哪些节点属于并行组（包含 branch/replaced，全部参与居中）
    const parallelNodeIds = new Set<string>()
    parallelGroups.forEach(group => {
      group.forEach(n => parallelNodeIds.add(n.id))
    })

    // 按 step_index 分组，处理同 step 多节点（Observe/Answer 等）
    const stepGroups = new Map<number, AgentNode[]>()
    activeNodes.forEach(node => {
      if (!stepGroups.has(node.step_index)) stepGroups.set(node.step_index, [])
      stepGroups.get(node.step_index)!.push(node)
    })

    activeNodes.forEach((node) => {
      const colorScheme = NODE_COLORS[node.type] || { bg: '#f0f0f0', border: '#d9d9d9', label: node.type }
      const isPending = node.status === 'pending'
      const isBranch = node.status === 'branch'
      const isReplaced = node.status === 'replaced'
      const isDeprecated = isBranch || isReplaced
      const isParallel = parallelNodeIds.has(node.id)

      // 布局：并行节点等间距居中，branch/replaced 排最左
      // 非并行但同 step 多节点（Observe/Answer）也等间距，replaced 排最左
      let xPosition = centerX - 100
      let yPosition = node.step_index * spacingY

      if (isParallel) {
        const pgId = node.data?.parallel_group_id
        const group = parallelGroups.get(pgId!)
        if (group) {
          // 排序：branch/replaced 排最左，其余按原序
          const sorted = group.slice().sort((a, b) => {
            const aBad = a.status === 'branch' || a.status === 'replaced'
            const bBad = b.status === 'branch' || b.status === 'replaced'
            if (aBad && !bBad) return -1
            if (!aBad && bBad) return 1
            return 0
          })
          const idx = sorted.findIndex(n => n.id === node.id)
          xPosition = centerX - 100 + (idx - (sorted.length - 1) / 2) * spacingX
        }
      } else if ((stepGroups.get(node.step_index)?.length ?? 1) > 1) {
        // 同 step 有多个节点，但不是并行组（Observe/Answer 等）
        const group = stepGroups.get(node.step_index)!.filter(n => {
          // 排除并行组节点，只考虑需要排布的
          return !parallelNodeIds.has(n.id)
        })
        if (group.length > 1) {
          const sorted = group.slice().sort((a, b) => {
            const aBad = a.status === 'branch' || a.status === 'replaced'
            const bBad = b.status === 'branch' || b.status === 'replaced'
            if (aBad && !bBad) return -1
            if (!aBad && bBad) return 1
            return 0
          })
          const idx = sorted.findIndex(n => n.id === node.id)
          xPosition = centerX - 100 + (idx - (sorted.length - 1) / 2) * spacingX
        }
      }

      const flowNode: Node = {
        id: node.id,
        position: { x: xPosition, y: yPosition },
        data: {
          label: node.label,
          type: node.type,
          status: node.status,
          data: node.data,
          color: colorScheme,
          isBranch,
          isReplaced,
          isParallel,
        },
        style: {
          background: isPending ? '#fafafa' : isDeprecated ? '#f5f5f5' : colorScheme.bg,
          border: isPending ? `2px dashed ${colorScheme.border}` : isParallel ? `3px solid ${colorScheme.border}` : `2px solid ${isDeprecated ? '#d9d9d9' : colorScheme.border}`,
          borderRadius: '8px',
          padding: '12px',
          minWidth: '200px',
          opacity: isDeprecated ? 0.5 : isPending ? 0.6 : 1,
          boxShadow: isPending ? 'none' : '0 2px 8px rgba(0,0,0,0.08)',
        },
      }

      if (node.status === 'pending') {
        console.log('[flowNodes] PENDING node:', {
          id: flowNode.id,
          type: node.type,
          position: flowNode.position,
          label: node.label,
        })
      }

      nodes.push(flowNode)
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

      // 检查目标节点是否为 replaced
      const targetNode = graph.value.nodes.find(n => n.id === edge.to)
      const isReplacedEdge = targetNode?.status === 'replaced'

      const isDimmed = isBranchEdge || isReplacedEdge

      edges.push({
        id: `edge_${idx}`,
        source: edge.from,
        target: edge.to,
        animated: isBranchEdge ? false : isPendingEdge ? style.animated : style.animated,
        style: {
          stroke: isDimmed ? '#d9d9d9' : style.color,
          strokeWidth: isDimmed ? 1 : 2,
          ...(isDimmed ? { strokeDasharray: '4,4' } : (style.dashed ? { strokeDasharray: '5,5' } : {})),
        },
        markerEnd: isBranchEdge || isPendingEdge || isReplacedEdge
          ? undefined
          : {
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
