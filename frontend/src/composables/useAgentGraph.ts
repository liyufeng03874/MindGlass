import {ref} from 'vue'
import type {AgentNode, AgentEdge, ReasoningGraph, SSEEvent} from '@/types/agent'

const API_BASE = 'http://localhost:8002'

let pendingIdCounter = 0

export function useAgentGraph() {
  const graph = ref<ReasoningGraph>({
    nodes: [],
    edges: [],
    branches: [],
    meta: { current_step_index: 0, total_steps: 0, query: '', run_id: '' },
  })
  const status = ref('')
  const connected = ref(false)
  const isRunning = ref(false)

  const messages = ref<Array<{ role: 'user' | 'agent', content: string }>>([])

  function sendMessage(query: string) {
    messages.value.push({ role: 'user', content: query })
    status.value = '🤔 连接中...'
    connected.value = true
    isRunning.value = true

    // 重置图状态
    graph.value = {
      nodes: [],
      edges: [],
      branches: [],
      meta: { current_step_index: 0, total_steps: 0, query: '', run_id: '' },
    }

    // 立即显示 pending "规划中..." 节点
    pendingIdCounter++
    graph.value.nodes.push({
      id: `frontend_pending_${pendingIdCounter}`,
      type: 'Plan',
      data: { pending: true, label: '规划中...' },
      status: 'pending',
      step_index: 0,
      branch_id: null,
      label: '规划中...',
    })

    const eventSource = new EventSource(
      `${API_BASE}/api/run?query=${encodeURIComponent(query)}`
    )

    eventSource.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as SSEEvent
        handleEvent(parsed)
      } catch (e) {
        console.error('SSE parse error:', e)
      }
    }

    eventSource.onerror = () => {
      status.value = '连接断开'
      connected.value = false
      isRunning.value = false
      eventSource.close()
    }
  }

  function handleEvent(event: SSEEvent) {
    console.log('[SSE]', event.type, event.data)
    switch (event.type) {
      case 'status':
        status.value = event.data.message
        break

      case 'node_complete': {
        const node = event.data.node as AgentNode

        // 后端返回完整图，直接覆盖
        if (event.data.graph?.nodes) {
          const backendNodes = event.data.graph.nodes
          const oldPendings = graph.value.nodes.filter(n => n.status === 'pending')

          // 对每个 pending，检查后端是否已有足够数量的同 step_index 同类型节点
          // 如果有，说明该 pending 已被真实节点替代，不再保留
          const survivingPendings = oldPendings.filter(p => {
            if (p.step_index === undefined) return true
            const pendingCount = oldPendings.filter(
              q => q.step_index === p.step_index && q.type === p.type
            ).length
            const realCount = backendNodes.filter(
              n => n.step_index === p.step_index && n.type === p.type && n.status !== 'pending'
            ).length
            // 真实节点数 >= pending数，说明全部被替代，清除
            return realCount < pendingCount
          })

          const survivingPendingIds = new Set(survivingPendings.map(n => n.id))
          const survivingEdges = graph.value.edges.filter(
            e => survivingPendingIds.has(e.from) || survivingPendingIds.has(e.to)
          )

          graph.value.nodes = [...backendNodes, ...survivingPendings]
          graph.value.edges = [...(event.data.graph.edges || []), ...survivingEdges]
        } else {
          graph.value.nodes.push(node)
          const activeNodes = graph.value.nodes.filter(
            n => n.status !== 'branch' && n.status !== 'discarded' && n.id !== node.id
          )
          if (activeNodes.length > 0) {
            const prevNode = activeNodes[activeNodes.length - 1]
            graph.value.edges.push({
              from: prevNode.id,
              to: node.id,
              type: 'Normal',
            })
          }
        }

        // 追加 pending 节点
        if (node.type === 'Plan') {
          pushPendingNode(node)
        } else if (event.data.graph?.nodes && node.type === 'Observe') {
          const backendNodes = event.data.graph.nodes
          const planNode = backendNodes.find(n => n.type === 'Plan' && n.status !== 'pending')
          const totalSteps = planNode?.data?.steps?.length || 0
          const realToolCalls = backendNodes.filter(
            n => n.type === 'ToolCall' && n.status !== 'pending'
          ).length

          // 所有 ToolCall 已完成 → 推 Answer pending（仅此一次）
          if (realToolCalls >= totalSteps && totalSteps > 0) {
            pushPendingAnswer(node)
          }
        }

        if (node.type === 'Answer') {
          messages.value.push({ role: 'agent', content: node.data.output })
          status.value = '✅ 完成'
          isRunning.value = false
        } else {
          status.value = `已生成 ${node.type} 节点`
        }
        break
      }

      case 'run_complete': {
        connected.value = false
        isRunning.value = false
        if (event.data.graph) {
          console.log('[Run Complete] edges:', JSON.stringify(event.data.graph.edges, null, 2))
          graph.value = event.data.graph as ReasoningGraph
          console.log('[Run Complete]', graph.value.nodes.length, 'nodes', graph.value.edges.length, 'edges')
        }
        break
      }

      case 'error':
        status.value = `❌ 错误: ${event.data.message}`
        connected.value = false
        isRunning.value = false
        break
    }
  }

  /** 前端自动推 pending 虚拟节点 */
  function pushPendingNode(prevNode: AgentNode) {
    const planNode = graph.value.nodes.find(n => n.type === 'Plan' && n.status !== 'pending')
    if (!planNode?.data?.steps || !Array.isArray(planNode.data.steps)) {
      return
    }

    const steps = planNode.data.steps as Array<{ tool: string }>
    const totalSteps = steps.length

    if (prevNode.type === 'Plan') {
      // Plan 完成后，一次性创建所有 pending ToolCall 节点（并行组）
      const parallelGroupId = `pg_pending_${Date.now().toString(36)}`
      steps.forEach((step, idx) => {
        pendingIdCounter++
        const pendingNode: AgentNode = {
          id: `frontend_pending_${pendingIdCounter}`,
          type: 'ToolCall',
          data: { pending: true, label: step.tool, parallel_group_id: parallelGroupId },
          status: 'pending',
          step_index: 1,  // 并行组共享 step_index
          branch_id: null,
          label: step.tool,
        }
        graph.value.nodes.push(pendingNode)
        graph.value.edges.push({
          from: prevNode.id,
          to: pendingNode.id,
          type: 'Pending',
        })
      })
      graph.value.nodes = [...graph.value.nodes]
      graph.value.edges = [...graph.value.edges]
      return
    }

    let nextType: string
    let nextLabel = ''

    if (prevNode.type === 'ToolCall') {
      nextType = 'Observe'
      nextLabel = '观察结果'
    } else if (prevNode.type === 'Observe') {
      nextType = 'Answer'
      nextLabel = '最终回答'
    } else {
      return
    }

    pendingIdCounter++
    const pendingNode: AgentNode = {
      id: `frontend_pending_${pendingIdCounter}`,
      type: nextType as AgentNode['type'],
      data: { pending: true, label: nextLabel },
      status: 'pending',
      step_index: prevNode.step_index + 1,
      branch_id: prevNode.branch_id,
      label: nextLabel,
    }

    graph.value.nodes.push(pendingNode)
    graph.value.edges.push({
      from: prevNode.id,
      to: pendingNode.id,
      type: 'Pending',
    })
    graph.value.nodes = [...graph.value.nodes]
    graph.value.edges = [...graph.value.edges]
  }

  /** 只推 Answer pending */
  function pushPendingAnswer(prevNode: AgentNode) {
    pendingIdCounter++
    const pendingNode: AgentNode = {
      id: `frontend_pending_${pendingIdCounter}`,
      type: 'Answer',
      data: { pending: true, label: '最终回答' },
      status: 'pending',
      step_index: prevNode.step_index + 1,
      branch_id: prevNode.branch_id,
      label: '最终回答',
    }

    graph.value.nodes.push(pendingNode)
    graph.value.edges.push({
      from: prevNode.id,
      to: pendingNode.id,
      type: 'Pending',
    })
    graph.value.nodes = [...graph.value.nodes]
    graph.value.edges = [...graph.value.edges]
  }

  /** 从指定 step_index 重试（支持编辑后重跑） */
  async function retryFrom(stepIndex: number, originalNode: any, editedData?: Record<string, any>) {
    // 检测：如果是 ToolCall 类型且属于并行组，走方案 C
    const isParallelGroup = originalNode?.data?.parallel_group_id

    if (isParallelGroup) {
      // 方案 C：并行重试，只重跑被点击的那个
      return retryFromGraph(stepIndex, originalNode, editedData)
    }

    // 普通串行重试
    status.value = '🔄 正在重试...'
    connected.value = true
    isRunning.value = true

    const response = await fetch(`${API_BASE}/api/retry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step_index: stepIndex, edited_data: editedData }),
    })

    if (!response.ok) {
      status.value = `❌ 重试失败: HTTP ${response.status}`
      connected.value = false
      isRunning.value = false
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      status.value = '❌ SSE 读取失败'
      connected.value = false
      isRunning.value = false
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const parsed = JSON.parse(line.slice(6)) as SSEEvent
            handleEvent(parsed)
          } catch (e) {
            console.error('SSE parse error:', e)
          }
        }
      }
    }
  }

  /** 方案 C：并行重试——被编辑的旧节点废弃推远，新节点占原位 */
  async function retryFromGraph(stepIndex: number, originalNode: any, editedData?: Record<string, any>) {
    status.value = '🔄 正在并行重试...'
    connected.value = true
    isRunning.value = true

    // 旧节点：只有被编辑的那个（将废弃并推到远位置）
    const oldNode = {
      ...originalNode,
      data: {
        ...originalNode.data,
        original: 'old' as const,
      },
    }

    // 新节点：编辑后的版本（占据原位置）
    const newNode = {
      ...originalNode,
      data: {
        ...originalNode.data,
        tool: editedData?.tool || originalNode.data?.tool,
        params: editedData?.params || originalNode.data?.params,
        original: 'new' as const,
      },
    }

    // 获取 query 和 plan_info
    const planNode = graph.value.nodes.find(n => n.type === 'Plan' && n.status !== 'pending')
    const query = planNode?.data?.input || ''
    const planInfo = planNode?.data?.output || ''

    const response = await fetch(`${API_BASE}/api/retry_from_graph`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        step_index: stepIndex,
        old_nodes: [oldNode],
        new_nodes: [newNode],
        query,
        plan_info: planInfo,
      }),
    })

    if (!response.ok) {
      status.value = `❌ 重试失败: HTTP ${response.status}`
      connected.value = false
      isRunning.value = false
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      status.value = '❌ SSE 读取失败'
      connected.value = false
      isRunning.value = false
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const parsed = JSON.parse(line.slice(6)) as SSEEvent
            handleEvent(parsed)
          } catch (e) {
            console.error('SSE parse error:', e)
          }
        }
      }
    }
  }

  return {
    graph,
    status,
    connected,
    isRunning,
    messages,
    sendMessage,
    retryFrom,
    retryFromGraph,
    pushPendingNode,
  }
}
