import { ref, computed } from 'vue'
import type { SSEEvent, ReasoningGraph, AgentNode, AgentEdge } from '@/types/agent'

const API_BASE = 'http://localhost:8002'

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
    switch (event.type) {
      case 'status':
        status.value = event.data.message
        break

      case 'node_complete': {
        const node = event.data.node as AgentNode
        graph.value.nodes.push(node)

        // 如果是 Answer 节点，添加到消息列表
        if (node.type === 'Answer') {
          messages.value.push({ role: 'agent', content: node.data.output })
          status.value = '✅ 完成'
          isRunning.value = false
        } else {
          status.value = `已生成 ${node.type} 节点`
        }

        // 自动添加边（连接到上一个节点）
        const activeNodes = graph.value.nodes.filter(
          n => n.status !== 'discarded' && n.id !== node.id
        )
        if (activeNodes.length > 0) {
          const prevNode = activeNodes[activeNodes.length - 1]
          graph.value.edges.push({
            from: prevNode.id,
            to: node.id,
            type: node.status === 'branch' ? 'Branch' : 'Normal',
          })
        }
        break
      }

      case 'run_complete': {
        connected.value = false
        isRunning.value = false
        if (event.data.graph) {
          graph.value = event.data.graph as ReasoningGraph
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

  return {
    graph,
    status,
    connected,
    isRunning,
    messages,
    sendMessage,
  }
}
