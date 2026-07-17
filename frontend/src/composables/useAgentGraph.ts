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
    // console.log('[SSE]', event.type, event.data)
    switch (event.type) {
      case 'status':
        status.value = event.data.message
        break

      case 'node_complete': {
        const node = event.data.node as AgentNode

        // 后端返回完整图，直接覆盖
        if (event.data.graph?.nodes) {
          graph.value.nodes = event.data.graph.nodes
          graph.value.edges = event.data.graph.edges || []
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

        // 追加 1 个 pending
        if (node.type !== 'Answer') {
          pushPendingNode(node)
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

    // 并行场景：用已完成的 Observe 数量判断
    const completedObs = graph.value.nodes.filter(
      n => n.type === 'Observe' && n.status === 'done'
    ).length

    let nextType: string
    let nextLabel = ''

    if (prevNode.type === 'Plan') {
      nextType = steps.length > 0 ? 'ToolCall' : 'Answer'
      nextLabel = steps.length > 0 ? steps[0].tool : '最终回答'
    } else if (prevNode.type === 'ToolCall') {
      nextType = 'Observe'
      nextLabel = '观察结果'
    } else if (prevNode.type === 'Observe') {
      if (completedObs >= totalSteps) {
        // 所有工具已完成 → Answer
        nextType = 'Answer'
        nextLabel = '最终回答'
      } else {
        // 还有步骤未执行
        const nextStep = steps[completedObs]
        if (nextStep) {
          nextType = 'ToolCall'
          nextLabel = nextStep.tool
        } else {
          nextType = 'Answer'
          nextLabel = '最终回答'
        }
      }
    } else {
      return
    }

    // 只拦 pending ToolCall：所有工具已完成时不推 ToolCall
    if (nextType === 'ToolCall' && completedObs >= totalSteps) return

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
      type: 'Pending' as any,
    })
    graph.value.nodes = [...graph.value.nodes]
    graph.value.edges = [...graph.value.edges]
  }

  /** 从指定 step_index 重试（支持编辑后重跑） */
  async function retryFrom(stepIndex: number, editedData?: Record<string, any>) {
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

  return {
    graph,
    status,
    connected,
    isRunning,
    messages,
    sendMessage,
    retryFrom,
    pushPendingNode,
  }
}
