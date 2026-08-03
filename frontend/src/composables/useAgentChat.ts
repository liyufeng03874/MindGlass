import { ref } from 'vue'
import type { SSEEvent } from '@/types/agent'

// API 地址：生产环境通过 nginx 反代 /api，开发环境可覆盖 VITE_API_BASE_URL
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export function useAgentChat() {
  const messages = ref<Array<{ role: 'user' | 'agent', content: string }>>([])
  const status = ref('')
  const connected = ref(false)

  function sendMessage(query: string) {
    messages.value.push({ role: 'user', content: query })
    status.value = '连接中...'
    connected.value = true

    const eventSource = new EventSource(`${API_BASE}/api/run?query=${encodeURIComponent(query)}`)

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
      eventSource.close()
    }
  }

  function handleEvent(event: SSEEvent) {
    switch (event.type) {
      case 'status':
        status.value = event.data.message
        break
      case 'node_complete':
        const node = event.data.node
        if (node.type === 'Answer') {
          messages.value.push({ role: 'agent', content: node.data.output })
          status.value = '完成'
        }
        break
      case 'run_complete':
        connected.value = false
        break
      case 'error':
        status.value = `错误: ${event.data.message}`
        connected.value = false
        break
    }
  }

  return { messages, status, connected, sendMessage }
}
