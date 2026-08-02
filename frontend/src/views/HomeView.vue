<template>
  <div class="mindglass">
    <header class="header">
      <h1>🧠 MindGlass</h1>
      <span class="subtitle">可观测多步推理 Agent</span>
      <div class="status-bar">
        <span :class="['status-dot', { active: connected }]"></span>
        <span>{{ status || '就绪' }}</span>
        <template v-if="graph.nodes.length === 0">
          <input
            v-model="demoInput"
            class="demo-input"
            placeholder="1"
            @keydown.enter="loadTestData(demoInput || undefined)"
          />
          <button
            class="toggle-graph-btn"
            @click="loadTestData(demoInput || undefined)"
            :disabled="demoLoaded || loadingDemo"
          >
            📦 加载测试数据
          </button>
        </template>
        <template v-else>
          <button
            class="clear-btn"
            @click="clearDemo"
          >
            🗑️ 清空
          </button>
          <button
            class="toggle-graph-btn"
            @click="showGraph = !showGraph"
          >
            {{ showGraph ? '👁️ 隐藏思维' : '💡 思维可视化' }}
          </button>
        </template>
        <!-- Admin 入口 -->
        <router-link to="/admin" class="admin-link">🔧 后台管理</router-link>
      </div>
    </header>

    <main class="main-content">
      <div :class="['left-panel', { full: !showGraph }]">
        <ChatPanel
          ref="chatPanelRef"
          :messages="messages"
          :disabled="isRunning"
          :statusText="status"
          :totalElapsed="isRunning ? null : totalElapsed"
          @send="onSend"
          :initialGreeting="initialGreeting"
        />
      </div>
      <transition name="slide">
        <div v-if="showGraph" class="right-panel">
          <ReasoningGraph :graph="graph" :isRunning="isRunning" @retry="onRetry" @focus-answer="onFocusAnswer" />
        </div>
      </transition>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import ChatPanel from '../components/ChatPanel.vue'
import ReasoningGraph from '../components/ReasoningGraph.vue'
import { useAgentGraph } from '../composables/useAgentGraph'

const { graph, status, connected, messages, isRunning, sendMessage, retryFrom } = useAgentGraph()

/** 总运行耗时（从 meta.run_started_at 计算） */
const totalElapsed = ref<string | null>(null)
let elapsedTimer: ReturnType<typeof setInterval> | null = null

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}m${s.toFixed(0)}s`
}

/** 启动/停止总用时定时器 */
function watchElapsed(active: boolean) {
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
  if (active && graph.value?.meta?.run_started_at) {
    const startedAt = graph.value.meta.run_started_at * 1000 // 秒→毫秒
    elapsedTimer = setInterval(() => {
      totalElapsed.value = formatElapsed((Date.now() - startedAt) / 1000)
    }, 100)
  }
}

// 监听 isRunning 和 graph.meta.run_started_at 变化
watch([isRunning, () => graph.value?.meta?.run_started_at], ([running, startedAt]) => {
  // demo 加载时已经手动算过耗时了，watch 不要覆盖
  if (demoElapsedLocked.value) return
  if (running && startedAt) {
    watchElapsed(true)
  } else if (!running) {
    // 运行结束，显示最终值
    if (graph.value?.meta?.run_started_at) {
      const startedAt = graph.value.meta.run_started_at * 1000
      totalElapsed.value = formatElapsed((Date.now() - startedAt) / 1000)
    }
    watchElapsed(false)
  }
}, { immediate: false })

const showGraph = ref(false)
const chatPanelRef = ref<InstanceType<typeof ChatPanel> | null>(null)
const demoInput = ref('')
const demoLoaded = ref(false)
const loadingDemo = ref(false)
/** demo 加载时手动算过耗时，watch 不要覆盖 */
const demoElapsedLocked = ref(false)
const initialGreeting = '你好，我是 MindGlass 🧠\n\n我可以帮你拆解复杂问题、调用工具搜索、生成结构化回答。试试问我点什么吧～'

function onSend(query: string) {
  sendMessage(query)
  // 第一次发送消息时，展示右侧推理面板
  if (!showGraph.value) {
    showGraph.value = true
  }
}

function onRetry(stepIndex: number, originalNode: any, editedData: Record<string, any>) {
  retryFrom(stepIndex, originalNode, editedData)
}

function onFocusAnswer() {
  if (chatPanelRef.value) {
    chatPanelRef.value.highlightLastMessage()
  }
}

function loadTestData(demoName: string = '1') {
  if (demoLoaded.value) return // 已加载过，必须先清空

  loadingDemo.value = true
  // 调用后端加载 demo 数据，直接返回 graph
  fetch(`${import.meta.env.VITE_API_BASE_URL || '/api'}/load-demo?demo=${demoName}`, { method: 'POST' })
    .then(res => res.json())
    .then(data => {
      graph.value = data.graph
      showGraph.value = true
      demoLoaded.value = true

      // 提取 Answer 节点的 output 填充到聊天
      const answerNode = data.graph?.nodes?.find((n: any) => n.type === 'Answer' && n.status === 'done')
        || data.graph?.nodes?.find((n: any) => n.type === 'Answer' && n.status !== 'replaced')
      if (answerNode?.data?.output) {
        messages.value.push({
          role: 'user',
          content: answerNode.data.input || '测试问题',
        })
        messages.value.push({
          role: 'agent',
          content: answerNode.data.output,
        })
      }

      // 计算总耗时：用各节点 duration_ms 之和
      const nodes = data.graph?.nodes || []
      const totalMs = nodes.reduce((sum: number, n: any) => sum + (n.duration_ms || 0), 0)
      const totalSec = totalMs / 1000
      if (totalSec > 0) {
        if (totalSec < 60) {
          totalElapsed.value = `${totalSec.toFixed(1)}s`
        } else {
          const m = Math.floor(totalSec / 60)
          const s = totalSec % 60
          totalElapsed.value = `${m}m${s.toFixed(0)}s`
        }
      }
      demoElapsedLocked.value = true

      status.value = `📦 已加载 ${demoName} 测试数据`
    })
    .catch(() => {
      status.value = '❌ 加载测试数据失败'
    })
    .finally(() => {
      loadingDemo.value = false
    })
}

function clearDemo() {
  graph.value = { nodes: [], edges: [] }
  messages.value = []
  showGraph.value = false
  demoLoaded.value = false
  demoElapsedLocked.value = false
  totalElapsed.value = null
  status.value = '就绪'
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #f5f7fa;
  color: #333;
}

.mindglass {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  background: #fff;
  padding: 12px 24px;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  gap: 16px;
}

.header h1 {
  font-size: 20px;
  color: #1a1a2e;
}

.subtitle {
  font-size: 13px;
  color: #888;
}

.status-bar {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: #666;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ccc;
}

.status-dot.active {
  background: #52c41a;
  animation: pulse 1.5s infinite;
}

.demo-input {
  padding: 4px 8px;
  background: #fff;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  font-size: 13px;
  color: #333;
  width: 90px;
  outline: none;
  transition: border-color 0.2s;
}

.demo-input:focus {
  border-color: #52c41a;
}

.toggle-graph-btn {
  padding: 4px 12px;
  background: #f0f0f0;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #555;
  transition: all 0.2s;
}

.toggle-graph-btn:hover {
  background: #e8e8e8;
  color: #333;
}

.clear-btn {
  padding: 4px 12px;
  background: #ff4d4f;
  border: 1px solid #ff4d4f;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #fff;
  transition: all 0.2s;
}

.clear-btn:hover {
  background: #ff7875;
  border-color: #ff7875;
}

/* Admin 入口链接 */
.admin-link {
  padding: 4px 12px;
  background: #f0f0f0;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  font-size: 13px;
  color: #555;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s;
}

.admin-link:hover {
  background: #e8e8e8;
  color: #333;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.main-content {
  flex: 1;
  display: flex;
  gap: 0;
  overflow: hidden;
}

.left-panel {
  width: 50%;
  min-width: 640px;
  border-right: 1px solid #e8e8e8;
  background: #fff;
  transition: width 0.3s ease;
}

.left-panel.full {
  width: 100%;
  border-right: none;
}

.right-panel {
  flex: 1;
  background: #fafafa;
  position: relative;
}

/* 右侧面板滑入动画 */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.3s ease;
}

.slide-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.slide-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
