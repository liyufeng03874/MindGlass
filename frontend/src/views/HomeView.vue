<template>
  <div class="mindglass">
    <header class="header">
      <h1><MirrorIcon :size="22" class="title-icon" /> 思镜</h1>
      <span class="subtitle">照见思考的镜子 · 可观测多步推理 Agent</span>
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
          :leftBlocks="leftBlocks"
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
import { ref, watch, computed } from 'vue'
import ChatPanel from '../components/ChatPanel.vue'
import ReasoningGraph from '../components/ReasoningGraph.vue'
import MirrorIcon from '../components/MirrorIcon.vue'
import { useAgentGraph } from '../composables/useAgentGraph'
import { usePhase, derivePhase } from '../composables/usePhase'

const { graph, status, connected, messages, isRunning, leftBlocks, sendMessage, retryFrom } = useAgentGraph()

// ── 全局相位：从推理状态推导，驱动整站氛围层呼吸（水镜 v2.1 第一遍）──
const { phase } = usePhase()
const hasNodes = computed(() => (graph.value?.nodes?.length ?? 0) > 0)
const derivedPhase = derivePhase(computed(() => isRunning.value), hasNodes)
watch(derivedPhase, (v) => { phase.value = v }, { immediate: true })

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

const showGraph = ref(true)
const chatPanelRef = ref<InstanceType<typeof ChatPanel> | null>(null)
const demoInput = ref('')
const demoLoaded = ref(false)
const loadingDemo = ref(false)
/** demo 加载时手动算过耗时，watch 不要覆盖 */
const demoElapsedLocked = ref(false)
const initialGreeting = '你好，我是思镜 ✨\n\n我是一面照见思考的镜子——把一个复杂问题拆成一步步推理，全过程摊开在你眼前。投一个问题进来，看思绪如何成形吧～'

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
    // 任务⑦ T2：优先用新的 answer block 聚焦函数
    if (chatPanelRef.value.highlightLastAnswerBlock) {
      chatPanelRef.value.highlightLastAnswerBlock()
    } else {
      chatPanelRef.value.highlightLastMessage()
    }
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
  graph.value = { nodes: [], edges: [], branches: [], meta: { current_step_index: 0, total_steps: 0, query: '', run_id: '' } }
  messages.value = []
  showGraph.value = true
  demoLoaded.value = false
  demoElapsedLocked.value = false
  totalElapsed.value = null
  status.value = '就绪'
}
</script>

<style>
/* 思镜 · 首页暗色玻璃主题（水镜 v2.1 第一遍）
   面板为半透明玻璃，右侧镜台全透——深空星野即水面 */
.mindglass {
  height: 100vh;
  display: flex;
  flex-direction: column;
  color: var(--text);
}

.header {
  background: var(--panel);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  padding: 12px 24px;
  border-bottom: 1px solid var(--panel-border);
  display: flex;
  align-items: center;
  gap: 16px;
  position: relative;
  z-index: 2;
}

.header h1 {
  font-size: 20px;
  color: var(--text-h);
  letter-spacing: 1px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-icon {
  color: var(--accent);
  filter: drop-shadow(0 0 8px rgba(167, 139, 250, 0.55));
}

.subtitle {
  font-size: 13px;
  color: var(--text-dim);
}

.status-bar {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: var(--text);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #3a3a4a;
}

.status-dot.active {
  background: var(--phase-tool);
  box-shadow: 0 0 8px var(--phase-tool);
  animation: pulse 1.5s infinite;
}

.demo-input {
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-h);
  width: 90px;
  outline: none;
  transition: border-color 0.2s;
}

.demo-input:focus {
  border-color: var(--accent);
}

.toggle-graph-btn {
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text);
  transition: all 0.2s;
}

.toggle-graph-btn:hover {
  background: rgba(167, 139, 250, 0.15);
  color: var(--text-h);
  border-color: var(--accent);
}

.clear-btn {
  padding: 4px 12px;
  background: rgba(255, 77, 79, 0.15);
  border: 1px solid rgba(255, 77, 79, 0.4);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #ff7875;
  transition: all 0.2s;
}

.clear-btn:hover {
  background: rgba(255, 77, 79, 0.28);
}

/* Admin 入口链接 */
.admin-link {
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text);
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s;
}

.admin-link:hover {
  background: rgba(167, 139, 250, 0.15);
  color: var(--text-h);
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

/* 左翼聊天：半透明玻璃，星空隐约透出（不加 backdrop-blur，以免抹平星点） */
.left-panel {
  width: 50%;
  min-width: 640px;
  border-right: 1px solid var(--panel-border);
  background: rgba(10, 14, 31, 0.5);
  transition: width 0.3s ease;
}

.left-panel.full {
  width: 100%;
  border-right: none;
}

/* 右侧镜台：全透，深空星野即水面，推理图浮于其上 */
.right-panel {
  flex: 1;
  background: transparent;
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
