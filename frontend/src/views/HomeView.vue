<template>
  <div class="mindglass">
    <header class="header">
      <div class="header-top">
        <h1><MirrorIcon :size="22" class="title-icon" /> 思镜</h1>
        <span class="subtitle">照见思考的镜子 · 可观测多步推理 Agent</span>
      </div>
      <div class="status-bar">
        <span :class="['status-dot', { active: connected }]"></span>
        <span>{{ status || '就绪' }}</span>
        <template v-if="graph.nodes.length === 0">
          <select
            v-model="selectedDemo"
            class="demo-select"
            :disabled="loadingDemo"
          >
            <option value="" disabled>选择测试用例...</option>
            <option v-for="d in demoList" :key="d.name" :value="d.name">{{ d.label }}</option>
          </select>
          <button
            class="toggle-graph-btn"
            @click="loadTestData(selectedDemo)"
            :disabled="!selectedDemo || demoLoaded || loadingDemo"
          >
            {{ loadingDemo ? '⏳ 加载中...' : '📦 加载' }}
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
            {{ showGraph ? '👁️ 隐藏' : '💡 思维' }}
          </button>
        </template>
        <!-- 场景选择：回退到入场页（仅进入对话后显示） -->
        <button
          v-if="entered"
          class="scene-back-btn"
          @click="backToScene"
        >
          🧭 场景选择
        </button>
        <!-- Admin 入口：新开标签页，不覆盖当前页 -->
        <a href="/admin" target="_blank" rel="noopener" class="admin-link">🔧</a>
      </div>
    </header>

    <main class="main-content" :class="{ 'show-graph': showGraph && isMobile, landing: !entered }">
      <!-- 入场页：未进入对话时显示（empty-state + 场景选择 + 直接输入） -->
      <div v-if="!entered" class="landing-overlay">
        <div class="landing-empty">
          <div class="empty-icon"><MirrorIcon :size="72" /></div>
          <p class="empty-title">投一个问题，看思绪成形</p>
          <p class="empty-sub">推理过程将如星河般在你眼前生长</p>
        </div>
        <div class="scene-selector">
          <div class="scene-head">
            <div class="scene-title">选择场景开始探索</div>
            <div class="scene-sub">思镜会根据问题类型自动调度 知识库检索 / 数据库分析 / 网络搜索</div>
          </div>
          <div class="scene-cards">
            <div
              v-for="sc in scenes"
              :key="sc.id"
              class="scene-card"
              :class="sc.id"
            >
              <div class="scene-card-head">
                <span class="scene-emoji">{{ sc.emoji }}</span>
                <span class="scene-name">{{ sc.name }}</span>
              </div>
              <div class="scene-desc">{{ sc.desc }}</div>
              <div class="scene-questions">
                <button
                  v-for="(q, qi) in sc.questions"
                  :key="qi"
                  class="scene-question"
                  :style="{ animationDelay: (qi * 0.4) + 's' }"
                  @click="onSceneQuestion(q)"
                >
                  <span class="q-icon">›</span>
                  <span class="q-text">{{ q }}</span>
                </button>
              </div>
            </div>
          </div>
          <button class="direct-input-btn" @click="onDirectEnter">
            不选场景，直接输入 <span class="direct-arrow">→</span>
          </button>
        </div>
      </div>

      <template v-if="entered">
        <div :class="['left-panel', { full: !showGraph || isMobile }]">
          <ChatPanel
            ref="chatPanelRef"
            :rounds="rounds"
            :disabled="isRunning"
            :statusText="status"
            :totalElapsed="isRunning ? null : totalElapsed"
            @send="onSend"
            :initialGreeting="initialGreeting"
          />
        </div>
        <transition name="slide">
          <div v-if="showGraph" class="right-panel">
            <ReasoningGraph
              :graph="graph"
              :isRunning="isRunning"
              :cutNodeId="cutNode?.id ?? null"
              :disconnected="disconnected"
              :autoRetrying="autoRetrying"
              :autoRetryCount="autoRetryCount"
              @retry="onRetry"
              @interrupt="onInterrupt"
              @focus-answer="onFocusAnswer"
              @reconnect="reconnect"
            />
          </div>
        </transition>
      </template>

      <!-- 手机端底部导航栏（仅进入对话后显示，入场页不显示） -->
      <div v-if="isMobile && entered" class="mobile-nav">
        <button
          :class="['nav-btn', { active: !showGraph }]"
          @click="showGraph = false"
        >💬 对话</button>
        <button
          :class="['nav-btn', { active: showGraph }]"
          @click="showGraph = true"
        >🧠 思维</button>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, onMounted, onUnmounted } from 'vue'
import ChatPanel from '../components/ChatPanel.vue'
import ReasoningGraph from '../components/ReasoningGraph.vue'
import MirrorIcon from '../components/MirrorIcon.vue'
import { useAgentGraph } from '../composables/useAgentGraph'
import { usePhase, derivePhase } from '../composables/usePhase'

// ── 手机端检测 ──
const isMobile = ref(false)
function checkMobile() {
  isMobile.value = window.innerWidth < 768
}
onMounted(async () => {
  checkMobile()
  window.addEventListener('resize', checkMobile)

  // ── 加载测试用例列表 ──
  fetch(`${import.meta.env.VITE_API_BASE_URL || '/api'}/list-demos`)
    .then(res => res.json())
    .then(data => { demoList.value = data.demos || [] })
    .catch(() => { /* 静默失败，下拉框为空 */ })

  // ── localStorage 重连：检测到未完成推理时弹窗询问 ──
  const pendingId = getPendingRunId()
  if (pendingId) {
    const shouldResume = confirm('检测到上次未完成的推理，是否恢复？\n\n点「确定」继续等待结果，点「取消」放弃并开始新对话。')
    if (shouldResume) {
      await resumePendingRun()
    } else {
      abandonPendingRun()
    }
  }
})
onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})

const { graph, status, connected, rounds, clearRounds, isRunning, cutNode, disconnected, autoRetrying, autoRetryCount, sendMessage, interrupt, clearCut, retryFrom, tryRestoreFromCache, reconnect, getPendingRunId, resumePendingRun, abandonPendingRun } = useAgentGraph()

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
const demoLoaded = ref(false)
const loadingDemo = ref(false)

// ── 测试用例下拉框 ──
interface DemoItem { name: string; label: string }
const demoList = ref<DemoItem[]>([])
const selectedDemo = ref('')
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

// ── 场景选择：三领域 + 预设问题（问题由哥哥提供，占位先跑通效果）──
interface Scene {
  id: string
  name: string
  emoji: string
  desc: string
  questions: string[]
}
const scenes = ref<Scene[]>([
  {
    id: 'legal',
    name: '法律',
    emoji: '⚖️',
    desc: '知识库检索 · 法条 / 案例 / 文书',
    questions: ['醉驾撞人一般怎么判，有类似案例吗？', '我想了解一些关于吸毒的案件判决结果？', '有没有故意伤人但由于态度良好而减轻量刑的事件？'],
  },
  {
    id: 'data',
    name: '数据',
    emoji: '📊',
    desc: '数据库分析 · 员工 / 订单 / 销售',
    questions: ['每个部门薪资最高的员工是谁', '各部门平均薪资排名', '销售额月度变化趋势'],
  },
  {
    id: 'general',
    name: '通用',
    emoji: '🌐',
    desc: '网络搜索 · 实时信息 / 新闻 / 对比',
    questions: ['2026年AI开发岗位怎么样？', '成都、杭州、北京生活成本对比', '介绍一下最近新出的Deepseek Harness'],
  },
])

// 是否已进入对话（true=正常左右布局，false=入场页）。
// 进入方式：选场景问题 / 直接输入。清空后回到入场页。
const entered = ref(false)

function onSceneQuestion(q: string) {
  entered.value = true
  onSend(q)
}

/** 直接输入入口：不选场景，进入正常聊天态（rounds 空 → 开场白 + 输入框自然出现） */
function onDirectEnter() {
  entered.value = true
  if (!showGraph.value) {
    showGraph.value = true
  }
}

/** 回退到入场页（清空当前对话） */
function backToScene() {
  clearDemo()
}

function onRetry(stepIndex: number, originalNode: any, editedData: Record<string, any>) {
  retryFrom(stepIndex, originalNode, editedData)
}

/** 运行中在指定节点处打断 */
function onInterrupt(node: any) {
  interrupt(node)
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

function loadTestData(demoName: string) {
  if (!demoName || demoLoaded.value) return // 未选择或已加载过，必须先清空

  loadingDemo.value = true
  // 调用后端加载 demo 数据，直接返回 graph
  fetch(`${import.meta.env.VITE_API_BASE_URL || '/api'}/load-demo?demo=${encodeURIComponent(demoName)}`, { method: 'POST' })
    .then(res => res.json())
    .then(data => {
      graph.value = data.graph
      showGraph.value = true
      demoLoaded.value = true

      // 提取 Answer 节点的 output 填充到聊天
      const answerNode = data.graph?.nodes?.find((n: any) => n.type === 'Answer' && n.status === 'done')
        || data.graph?.nodes?.find((n: any) => n.type === 'Answer' && n.status !== 'replaced')
      if (answerNode?.data?.output) {
        rounds.value.push({
          id: `round_demo_${Date.now()}`,
          query: answerNode.data.input || '测试问题',
          blocks: [],
          answer: answerNode.data.output,
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
  clearRounds()
  showGraph.value = true
  demoLoaded.value = false
  demoElapsedLocked.value = false
  selectedDemo.value = ''
  totalElapsed.value = null
  status.value = '就绪'
  clearCut()
  // 清空后回到入场页（完整闭环）
  entered.value = false
}
</script>

<style>
/* 思镜 · 首页暗色玻璃主题（水镜 v2.1 第一遍）
   面板为半透明玻璃，右侧镜台全透——深空星野即水面 */

/* ── 入场页（选择场景）── */
.landing-overlay {
  position: absolute;
  inset: 0;
  z-index: 3;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
  overflow-y: auto;
  pointer-events: auto;
  background: transparent; /* 全透：深空星野即入场页背景 */
}

/* empty-state 放大版（原在 ReasoningGraph 内，此处提到入场页顶部，整体上移150px） */
.landing-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  transform: translateY(-150px);
  margin-bottom: 36px;
  animation: scene-fade-in 0.7s ease both;
}

.landing-empty .empty-icon {
  color: var(--accent);
  filter: drop-shadow(0 0 24px rgba(167, 139, 250, 0.6));
  margin-bottom: 18px;
  animation: landing-float 4s ease-in-out infinite;
}

.landing-empty .empty-title {
  font-size: 26px;
  font-weight: 600;
  color: var(--text-h);
  letter-spacing: 2px;
}

.landing-empty .empty-sub {
  margin-top: 10px;
  font-size: 14px;
  color: var(--text-dim);
  letter-spacing: 1px;
}

@keyframes landing-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

.scene-selector {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  max-width: 1080px;
  animation: scene-fade-in 0.7s ease both;
  animation-delay: 0.1s;
}

.scene-head {
  text-align: center;
  margin-bottom: 28px;
}

.scene-title {
  font-size: 30px;
  font-weight: 600;
  color: var(--text-h);
  letter-spacing: 2px;
  text-shadow: 0 0 20px rgba(167, 139, 250, 0.35);
}

.scene-sub {
  margin-top: 10px;
  font-size: 14px;
  color: var(--text-dim);
}

.scene-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  width: 100%;
  max-width: 1080px;
}

.scene-card {
  background: var(--panel);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--panel-border);
  border-radius: 18px;
  padding: 26px 22px;
  transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
  animation: scene-card-in 0.6s ease both;
}

.scene-card:nth-child(1) { animation-delay: 0.15s; }
.scene-card:nth-child(2) { animation-delay: 0.25s; }
.scene-card:nth-child(3) { animation-delay: 0.35s; }

.scene-card:hover {
  transform: translateY(-3px);
  border-color: var(--accent);
  box-shadow: 0 8px 30px rgba(167, 139, 250, 0.15);
}

/* 场景选择回退按钮（右上角，仅进入对话后显示） */
.scene-back-btn {
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.scene-back-btn:hover {
  border-color: var(--accent);
  color: var(--text-h);
  background: rgba(167, 139, 250, 0.1);
}

/* 直接输入入口：低调次级按钮，三卡下方居中 */
.direct-input-btn {
  margin-top: 32px;
  padding: 12px 28px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.14);
  color: var(--text);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.25s ease;
  animation: scene-fade-in 0.7s ease both;
  animation-delay: 0.5s;
}

.direct-input-btn:hover {
  border-color: var(--accent);
  color: var(--text-h);
  background: rgba(167, 139, 250, 0.1);
  transform: translateY(-1px);
}

.direct-arrow {
  color: var(--accent);
  margin-left: 4px;
}

.scene-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.scene-emoji {
  font-size: 26px;
}

.scene-name {
  font-size: 19px;
  font-weight: 600;
  color: var(--text-h);
}

.scene-card.legal .scene-name { color: #fbbf24; }
.scene-card.data .scene-name { color: #60a5fa; }
.scene-card.general .scene-name { color: #34d399; }

.scene-desc {
  font-size: 13px;
  color: var(--text-dim);
  margin-bottom: 16px;
}

.scene-questions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 问题气泡：半透明胶囊 + 上下浮动 */
.scene-question {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 18px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text);
  font-size: 14px;
  text-align: left;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
  animation: scene-float 3.2s ease-in-out infinite;
}

.scene-question:hover {
  background: rgba(167, 139, 250, 0.14);
  border-color: var(--accent);
  color: var(--text-h);
  transform: translateY(-2px);
}

.q-icon {
  color: var(--accent);
  font-size: 16px;
  flex-shrink: 0;
}

.q-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@keyframes scene-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

@keyframes scene-card-in {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes scene-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@media (max-width: 860px) {
  .scene-cards {
    grid-template-columns: 1fr;
    max-width: 420px;
  }
  .scene-title { font-size: 20px; }
}

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

.header-top {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

@media (max-width: 768px) {
  .header {
    flex-direction: column;
    align-items: flex-start;
    padding: 10px 16px;
    gap: 8px;
  }
  .header h1 {
    font-size: 17px;
  }
  .subtitle {
    font-size: 11px;
  }
  .status-bar {
    width: 100%;
    flex-wrap: wrap;
    gap: 8px;
  }
  .admin-link {
    margin-left: auto;
    display: none;
  }
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

.demo-select {
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-h);
  min-width: 180px;
  max-width: 280px;
  outline: none;
  cursor: pointer;
  transition: border-color 0.2s;
}

.demo-select:focus {
  border-color: var(--accent);
}

.demo-select option {
  background: #1a1e3a;
  color: #e6e9f5;
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
  position: relative;
}

/* 左翼聊天：半透明玻璃，星空隐约透出（不加 backdrop-blur，以免抹平星点）
   进入对话时 mount，用 animation 从全透平滑渐变到半透明深色 + 分割线浮现 */
.left-panel {
  width: 50%;
  min-width: 320px;
  border-right: 1px solid var(--panel-border);
  background: rgba(10, 14, 31, 0.5);
  animation: chat-panel-in 0.6s ease;
}

@keyframes chat-panel-in {
  from {
    background: transparent;
    border-right-color: transparent;
  }
  to {
    background: rgba(10, 14, 31, 0.5);
    border-right-color: var(--panel-border);
  }
}

@media (max-width: 768px) {
  .left-panel {
    width: 100% !important;
    min-width: 100%;
    border-right: none;
  }
  .left-panel.full {
    height: 100%;
  }
  .right-panel {
    width: 100%;
    flex: unset;
  }
  .main-content {
    flex-direction: column;
    position: relative;
  }
  .main-content > .left-panel {
    height: 50%;
  }
  /* 对话 tab：左面板撑满 */
  .main-content:not(.show-graph) > .left-panel {
    height: calc(100% - 56px);
  }
  .main-content:not(.show-graph) > .right-panel {
    display: none;
  }
  .main-content > .right-panel {
    height: 50%;
    padding-bottom: 56px;
  }
  /* 手机端：推理图全屏时隐藏聊天 */
  .main-content.show-graph > .left-panel {
    display: none;
  }
  .main-content.show-graph > .right-panel {
    height: 100%;
  }
  /* 手机端底部导航 */
  .mobile-nav {
    display: flex;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 50;
    background: rgba(10, 14, 31, 0.95);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-top: 1px solid var(--panel-border);
    padding: 6px 8px;
    gap: 8px;
  }
  .nav-btn {
    flex: 1;
    padding: 10px 16px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    color: var(--text);
    font-size: 15px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .nav-btn.active {
    background: rgba(167, 139, 250, 0.15);
    border-color: var(--accent);
    color: var(--text-h);
  }
  /* 面板滑入动画：从下方进入 */
  .slide-enter-from {
    opacity: 0;
    transform: translateY(20px);
  }
  .slide-leave-to {
    opacity: 0;
    transform: translateY(20px);
  }
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
