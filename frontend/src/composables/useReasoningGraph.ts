import { computed, type ComputedRef } from 'vue'
import type { Node, Edge } from '@vue-flow/core'
import type { ReasoningGraph, AgentNode } from '@/types/agent'

/** 深空主题节点配色：半透明深色底 + 发光边框 + 浅色文字 */
const NODE_COLORS: Record<string, { bg: string; border: string; label: string }> = {
  Plan:      { bg: 'rgba(10,14,31,0.72)', border: '#60a5fa', label: '🧠 规划' },
  ToolCall:  { bg: 'rgba(10,14,31,0.72)', border: '#34d399', label: '🔧 执行' },
  Observe:   { bg: 'rgba(10,14,31,0.72)', border: '#fbbf24', label: '📡 观察' },
  Answer:    { bg: 'rgba(10,14,31,0.72)', border: '#c4b5fd', label: '💬 回答' },
  Decision:  { bg: 'rgba(10,14,31,0.72)', border: '#f59e0b', label: '⏳ 待决策' },
}

/** 深空主题边配色：低饱和柔色 */
const EDGE_STYLES: Record<string, { color: string; animated: boolean; dashed: boolean }> = {
  Normal:  { color: 'rgba(148,163,184,0.5)', animated: false, dashed: false },
  Retry:   { color: 'rgba(251,191,36,0.6)',  animated: true,  dashed: true },
  Fallback:{ color: 'rgba(248,113,113,0.5)', animated: true,  dashed: true },
  Branch:  { color: 'rgba(167,139,250,0.4)', animated: true,  dashed: true },
  Parallel:{ color: 'rgba(52,211,153,0.5)',  animated: false, dashed: false },
  Pending: { color: 'rgba(251,191,36,0.4)',  animated: true,  dashed: true },
}

export function useReasoningGraph(
  graph: ComputedRef<ReasoningGraph | null>,
  cutNodeId: ComputedRef<string | null> | null = null,
) {
  const flowNodes = computed<Node[]>(() => {
    if (!graph.value) return []

    // console.log('[flowNodes] graph.nodes count:', graph.value.nodes.length)
    // console.log('[flowNodes] pending nodes:', graph.value.nodes.filter(n => n.status === 'pending').map(n => n.id))

    const spacingY = 150  // 垂直间距（按 step_index）
    const centerX = 300   // 水平居中
    const branchOffsetX = -120  // branch 路径左偏移
    const newBranchOffsetX = 120  // 新路径右偏移
    const spacingX = 220  // 并行节点水平间距
    const rowSpacing = 320  // 同 step 多节点（非并行）行间距
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

    // 整组废弃的并行组：不让它占中心位，整组左移给活跃节点让路
    const allDeprecatedGroups = new Set<string>()
    parallelGroups.forEach((group, pgId) => {
      if (group.every(n => n.status === 'branch' || n.status === 'replaced')) {
        allDeprecatedGroups.add(pgId)
      }
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
      // 截断点节点：琥珀色高亮 + 呼吸动画，与废弃置灰区分开
      // 节点一旦进入废弃态（重试后旧截断点变 branch），不再套截断样式
      const isCut = !!cutNodeId?.value && cutNodeId.value === node.id
        && node.status !== 'branch' && node.status !== 'replaced' && node.status !== 'discarded'

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
          if (allDeprecatedGroups.has(pgId!)) {
            // 整组废弃：整体左移排布，把中心让给活跃节点
            xPosition = centerX - 100 - rowSpacing + (idx - (sorted.length - 1) / 2) * spacingX
          } else {
            xPosition = centerX - 100 + (idx - (sorted.length - 1) / 2) * spacingX
          }
        }
      } else if ((stepGroups.get(node.step_index)?.length ?? 1) > 1) {
        // 同 step 有多个节点，但不是并行组（Observe/Answer 等）
        const group = stepGroups.get(node.step_index)!.filter(n => {
          // 排除并行组节点，只考虑需要排布的
          return !parallelNodeIds.has(n.id)
        })
        if (group.length > 1) {
          // 非并行多节点同 step：废弃节点靠左、活跃节点居中
          const active = group.filter(n => n.status !== 'branch' && n.status !== 'replaced')
          const deprecated = group.filter(n => n.status === 'branch' || n.status === 'replaced')
          if (isDeprecated) {
            const dIdx = deprecated.findIndex(n => n.id === node.id)
            xPosition = centerX - 100 - rowSpacing * (deprecated.length - dIdx)
          } else {
            const aIdx = active.findIndex(n => n.id === node.id)
            xPosition = centerX - 100 + (aIdx - (active.length - 1) / 2) * rowSpacing
          }
        } else if (group.length === 1) {
          // 单个非并行节点与并行组共享 step_index：
          // 只有并行组里还有活跃节点时才左移让路；整组废弃时本节点占中心
          const hasActiveParallelSiblings = activeNodes.some(n =>
            n.step_index === node.step_index
            && parallelNodeIds.has(n.id)
            && !allDeprecatedGroups.has(n.data?.parallel_group_id)
          )
          if (hasActiveParallelSiblings) {
            xPosition = centerX - 100 - spacingX
          }
        }
      }

      const isDegraded = node.type === 'Answer' && node.data?.degraded === true
      const borderColor = isCut
        ? '#fbbf24'
        : isDegraded
          ? '#fa8c16'
          : (isDeprecated ? 'rgba(100,116,139,0.4)' : colorScheme.border)

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
          isDegraded,
          isDeprecated,
        },
        style: {
          background: isPending ? 'rgba(10,14,31,0.5)' : isDeprecated ? 'rgba(10,14,31,0.5)' : colorScheme.bg,
          backdropFilter: 'blur(8px)',
          border: isCut
            ? '2px solid #fbbf24'
            : isPending
              ? `1.5px dashed ${colorScheme.border}`
              : isParallel
                ? `2px solid ${borderColor}`
                : `1.5px solid ${borderColor}`,
          borderRadius: '8px',
          padding: '12px',
          minWidth: '200px',
          color: '#e6e9f5',
          opacity: isCut ? 1 : isDeprecated ? 0.45 : isPending ? 0.6 : 1,
          // 截断点的 boxShadow/animation 内联控制（不依赖 class diff，保证重试后能清除）
          boxShadow: isCut
            ? '0 0 14px rgba(251,191,36,0.5)'
            : isPending
              ? `0 0 6px ${colorScheme.border}40`
              : isDegraded
                ? '0 0 12px rgba(250,140,22,0.35)'
                : isDeprecated
                  ? 'inset 0 0 0 1px rgba(100,116,139,0.3)'
                  : `0 0 10px ${borderColor}30, 0 2px 12px rgba(0,0,0,0.4)`,
          ...(isDeprecated ? { backgroundImage: 'repeating-linear-gradient(45deg, transparent, transparent 10px, rgba(255,255,255,0.02) 10px, rgba(255,255,255,0.02) 20px)' } : {}),
          ...(isCut ? { animation: 'cutPulse 1.6s ease-in-out infinite' } : {}),
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

      // 检查边的任一端点是否为 branch/replaced——是则整条边置灰
      const targetNode = graph.value?.nodes.find(n => n.id === edge.to)
      const sourceNode = graph.value?.nodes.find(n => n.id === edge.from)
      const endpointDeprecated =
        targetNode?.status === 'replaced' || targetNode?.status === 'branch' ||
        sourceNode?.status === 'replaced' || sourceNode?.status === 'branch'

      const isDimmed = isBranchEdge || endpointDeprecated

      edges.push({
        id: `edge_${idx}`,
        source: edge.from,
        target: edge.to,
        // 直线连接：跨水平距离时默认贝塞尔会拐出大弯，直线更干净
        type: 'straight',
        animated: isBranchEdge ? false : isPendingEdge ? style.animated : style.animated,
        style: {
          stroke: isDimmed ? '#d9d9d9' : style.color,
          strokeWidth: isDimmed ? 1 : 2,
          ...(isDimmed ? { strokeDasharray: '4,4' } : (style.dashed ? { strokeDasharray: '5,5' } : {})),
        },
        markerEnd: isBranchEdge || isPendingEdge || endpointDeprecated
          ? undefined
          : {
              width: 12,
              height: 12,
              orient: 'auto',
              // @ts-ignore Vue Flow 的 EdgeMarker 类型定义不包含 refX/refY，但运行时有效
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
