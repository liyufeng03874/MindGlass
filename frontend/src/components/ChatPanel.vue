<template>
  <div class="chat-panel" :style="{ '--phase-border': phaseBorderColor }">
    <div class="messages" ref="messagesRef" @scroll="handleScroll">
      <!-- 开场白 -->
      <div v-if="rounds.length === 0 && initialGreeting" class="message agent greeting">
        <div class="avatar greeting-avatar"><MirrorIcon :size="26" /></div>
        <div class="bubble greeting-bubble">{{ initialGreeting }}</div>
      </div>

      <!-- ═══ 按轮次渲染：query → 本轮思考 blocks → 本轮最终回答 ═══ -->
      <template v-for="(round, ri) in rounds" :key="round.id">
        <!-- 用户问题 -->
        <div class="message user">
          <div class="avatar">👤</div>
          <div class="bubble">{{ round.query }}</div>
        </div>

        <!-- 本轮思考直播 blocks（最终回答出来后隐藏 answer 流式 block，避免重复） -->
        <ThoughtBlockList :blocks="visibleBlocks(round)" />

        <!-- 本轮最终回答 -->
        <div v-if="round.answer" class="message agent">
          <div class="avatar bot-avatar"><MirrorIcon :size="24" /></div>
          <div class="bubble" v-html="md.render(answerWithElapsed(round, ri))"></div>
        </div>
      </template>

      <div v-if="loading" class="message agent">
        <div class="avatar bot-avatar"><MirrorIcon :size="24" /></div>
        <div class="bubble thinking">{{ statusText || '正在规划...' }}</div>
      </div>
    </div>

    <!-- 回到底部按钮 -->
    <button v-if="showBackToBottom" class="back-to-bottom" @click="scrollToBottom">
      <span class="pc-text">↓ 回到底部</span>
      <span class="mobile-arrow">↓</span>
    </button>

    <div class="input-area">
      <input
        v-model="inputValue"
        @keyup.enter="handleSend"
        :disabled="disabled"
        placeholder="输入你的问题..."
        class="input"
      />
      <button @click="handleSend" :disabled="disabled || !inputValue.trim()" class="send-btn">
        发送
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed, onMounted, onUnmounted } from 'vue'
import MarkdownIt from 'markdown-it'
import * as echarts from 'echarts'
import type { Round, LeftBlock } from '../types/agent'
import { fixTooltipFormatter } from '../utils/echartsTooltip'
import MirrorIcon from './MirrorIcon.vue'
import ThoughtBlockList from './ThoughtBlockList.vue'
import { usePhase, phaseColor } from '../composables/usePhase'

const md = new MarkdownIt({ breaks: true, linkify: true })

// ── ECharts 自定义 fence 规则：```echarts 代码块 → 可渲染容器 ──
const defaultFence = md.renderer.rules.fence ||
  ((tokens: any[], idx: number, options: any, _env: any, self: any) => self.renderToken(tokens, idx, options))

md.renderer.rules.fence = (tokens: any[], idx: number, options: any, env: any, self: any) => {
  const token = tokens[idx]
  const info = token.info?.trim()
  if (info === 'echarts') {
    const content = token.content.trim()
    // 用 data-option 存原始 JSON，DOM 更新后由 initECharts 解析并渲染
    return `<div class="echarts-wrapper" data-echarts-option="${encodeURIComponent(content)}" style="width:100%;height:350px;margin:8px 0;border-radius:8px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);"></div>`
  }
  return defaultFence(tokens, idx, options, env, self)
}

// 让所有 Markdown 链接在新标签页打开，不抢走当前页面
const defaultLinkRender = md.renderer.rules.link_open ||
  ((tokens: any[], idx: number, options: any, _env: any, self: any) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens: any[], idx: number, options: any, env: any, self: any) => {
  const tIdx = tokens[idx].attrIndex('target')
  if (tIdx < 0) {
    tokens[idx].attrPush(['target', '_blank'])
    tokens[idx].attrPush(['rel', 'noopener noreferrer'])
  }
  return defaultLinkRender(tokens, idx, options, env, self)
}

const props = defineProps<{
  rounds: Round[]
  disabled?: boolean
  initialGreeting?: string
  statusText?: string
  totalElapsed?: string | null
}>()

const emit = defineEmits<{
  send: [query: string]
}>()

const inputValue = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const loading = computed(() => props.disabled)

// 水镜：左侧跟随右侧相位呼吸
const { phase } = usePhase()
const phaseBorderColor = computed(() => phaseColor(phase.value))

// ── ECharts 实例管理 ──
const chartInstances: Map<Element, echarts.ECharts> = new Map()

/** 扫描 DOM 中未初始化的 echarts-wrapper 并渲染图表 */
function initECharts() {
  nextTick(() => {
    const wrappers = document.querySelectorAll('.echarts-wrapper:not([data-initialized])')
    wrappers.forEach((el) => {
      const encoded = el.getAttribute('data-echarts-option')
      if (!encoded) return
      // 容器还没尺寸（移动端 tab 切换时 left-panel 被 display:none）→ 挂 ResizeObserver 等可见再 init
      if (el.clientWidth === 0 || el.clientHeight === 0) {
        try {
          const ro = new ResizeObserver(() => {
            if (el.clientWidth > 0 && el.clientHeight > 0) {
              ro.disconnect()
              initSingleChart(el as HTMLElement, encoded)
            }
          })
          ro.observe(el)
        } catch { /* ignore */ }
        return
      }
      initSingleChart(el as HTMLElement, encoded)
    })
  })
}

/** 初始化单个 echarts-wrapper */
function initSingleChart(el: HTMLElement, encoded: string) {
  if (el.getAttribute('data-initialized')) return
  try {
    const option = JSON.parse(decodeURIComponent(encoded))
    // 后端已生成深色主题 option，这里只做兑底
    option.backgroundColor = 'transparent'
    // ECharts 6 不支持 {@字段} 模板，编译成函数 formatter
    fixTooltipFormatter(option)
    const chart = echarts.init(el)
    chart.setOption(option)
    chartInstances.set(el, chart)
    el.setAttribute('data-initialized', 'true')
  } catch (e) {
    console.error('[ChatPanel] ECharts init failed:', e)
    el.innerHTML = '<span style="color:#f87171;font-size:12px;">图表渲染失败</span>'
  }
}

// ── MutationObserver: 监听 DOM 变化自动初始化 ECharts ──
let observer: MutationObserver | null = null

onMounted(() => {
  initECharts()
  // 用 MutationObserver 监听 messages 容器，任何 DOM 变化都扫描新 echarts-wrapper
  if (messagesRef.value) {
    observer = new MutationObserver(() => {
      initECharts()
    })
    observer.observe(messagesRef.value, { childList: true, subtree: true, characterData: true })
  }
  // 窗口 resize 时重排图表
  window.addEventListener('resize', handleResize)
  // 移动端 tab 切换回聊天时，强制重排 + 补 init 宽高为 0 的图表
  window.addEventListener('mindglass:charts-resize', handleResize)
})

onUnmounted(() => {
  observer?.disconnect()
  window.removeEventListener('resize', handleResize)
  window.removeEventListener('mindglass:charts-resize', handleResize)
  chartInstances.forEach(c => c.dispose())
  chartInstances.clear()
})

function handleResize() {
  // 重扫未初始化图表（容器刚有尺寸，ResizeObserver 异步可能未触发）
  initECharts()
  chartInstances.forEach(c => c.resize())
}

/** 最终回答已产生时，过滤掉本轮的 answer 流式 block（避免和回答气泡重复） */
function visibleBlocks(round: Round): LeftBlock[] {
  if (!round.answer) return round.blocks
  return round.blocks.filter(b => b.type !== 'answer')
}

/** 最后一轮的最终回答末尾追加总用时 */
function answerWithElapsed(round: Round, index: number): string {
  let content = round.answer ?? ''
  if (index === props.rounds.length - 1 && props.totalElapsed) {
    content += `\n\n---\n\n*（本次推理耗时 ${props.totalElapsed}）*`
  }
  return content
}

// ── 自动滚动：检测用户是否在底部 ──
const showBackToBottom = ref(false)
const isNearBottom = ref(true)

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

function isAtBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 60
}

function handleScroll() {
  if (messagesRef.value) {
    isNearBottom.value = isAtBottom(messagesRef.value)
    showBackToBottom.value = !isNearBottom.value
  }
}

function autoScroll() {
  if (isNearBottom.value && messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

// 轮次/block/流式内容/回答任何变化 → 贴底时自动滚到底
watch(
  () => {
    const rs = props.rounds || []
    const last = rs[rs.length - 1]
    if (!last) return 'empty'
    const lb = last.blocks[last.blocks.length - 1]
    return `${rs.length}|${last.blocks.length}|${lb?.content?.length ?? 0}|${(last.answer ?? '').length}`
  },
  () => nextTick(autoScroll)
)

function highlightLastMessage() {
  highlightLastAnswerBlock()
}

/** 聚焦最后一轮的回答气泡，播放高亮动画（可重复触发） */
function highlightLastAnswerBlock() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTo({
        top: messagesRef.value.scrollHeight,
        behavior: 'smooth',
      })
    }
    const bubbles = document.querySelectorAll('.message.agent .bubble')
    const el = bubbles[bubbles.length - 1]
    if (el) {
      el.classList.remove('highlighted')
      void (el as HTMLElement).offsetWidth  // 强制重绘，支持重复触发
      el.classList.add('highlighted')
      setTimeout(() => el.classList.remove('highlighted'), 2000)
    }
  })
}

defineExpose({ highlightLastMessage, highlightLastAnswerBlock })

function handleSend() {
  const query = inputValue.value.trim()
  if (!query) return
  emit('send', query)
  inputValue.value = ''
}
</script>

<style scoped>
.chat-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  /* 水镜：左侧边框跟随右侧相位呼吸 */
  border-right: 2px solid var(--phase-border, var(--panel-border));
  transition: border-color 0.8s ease;
  box-shadow: inset -1px 0 8px rgba(167, 139, 250, 0.05);
  position: relative;
}

.messages {
  flex: 1;
  min-height: 0;  /* 关键：flex 子项才能被压缩到小于内容高度，overflow 才能生效 */
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  scrollbar-width: thin;
  scrollbar-color: rgba(167, 139, 250, 0.35) rgba(255, 255, 255, 0.04);
}

.messages::-webkit-scrollbar { width: 8px; }
.messages::-webkit-scrollbar-track { background: rgba(255, 255, 255, 0.04); border-radius: 4px; }
.messages::-webkit-scrollbar-thumb { background: rgba(167, 139, 250, 0.35); border-radius: 4px; }
.messages::-webkit-scrollbar-thumb:hover { background: rgba(167, 139, 250, 0.6); }

@media (max-width: 768px) {
  .messages {
    padding: 12px;
    gap: 10px;
  }
}

/* 关键：直接子元素永不压缩——内容超出时由容器滚动，而不是挤压板块 */
.messages > * {
  flex-shrink: 0;
}

.message {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.message.user {
  flex-direction: row-reverse;
}

.avatar {
  font-size: 24px;
  flex-shrink: 0;
}

.greeting-avatar {
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  filter: drop-shadow(0 0 8px rgba(167, 139, 250, 0.5));
}

.bot-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  filter: drop-shadow(0 0 6px rgba(167, 139, 250, 0.4));
}

.bubble {
  text-align: left;
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

@media (max-width: 768px) {
  .bubble {
    max-width: 90%;
    font-size: 15px;
    padding: 12px 16px;
  }
}

.message.user .bubble {
  background: linear-gradient(135deg, #a78bfa 0%, #8b6ff0 100%);
  color: #fff;
  border-bottom-right-radius: 4px;
  box-shadow: 0 2px 12px rgba(167, 139, 250, 0.25);
}

.message.agent .bubble {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-h);
  border: 1px solid var(--panel-border);
  border-bottom-left-radius: 4px;
  backdrop-filter: blur(8px);
}

/* Agent 消息的 Markdown 样式 */
.message.agent .bubble :deep(h1),
.message.agent .bubble :deep(h2),
.message.agent .bubble :deep(h3),
.message.agent .bubble :deep(h4) {
  margin: 0.8em 0 0.4em;
  font-weight: 600;
  line-height: 1.3;
}
.message.agent .bubble :deep(h1) { font-size: 1.25em; }
.message.agent .bubble :deep(h2) { font-size: 1.15em; }
.message.agent .bubble :deep(h3) { font-size: 1.05em; }
.message.agent .bubble :deep(h1):first-child,
.message.agent .bubble :deep(h2):first-child,
.message.agent .bubble :deep(h3):first-child { margin-top: 0; }

.message.agent .bubble :deep(p) {
  margin: 0.4em 0;
}
.message.agent .bubble :deep(p):first-child { margin-top: 0; }
.message.agent .bubble :deep(p):last-child { margin-bottom: 0; }

.message.agent .bubble :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.5em 0;
  font-size: 0.9em;
}
.message.agent .bubble :deep(th),
.message.agent .bubble :deep(td) {
  border: 1px solid rgba(255, 255, 255, 0.12);
  padding: 6px 10px;
  text-align: left;
}
.message.agent .bubble :deep(th) {
  background: rgba(255, 255, 255, 0.08);
  font-weight: 600;
}
.message.agent .bubble :deep(tr:nth-child(even)) {
  background: rgba(255, 255, 255, 0.02);
}

.message.agent .bubble :deep(blockquote) {
  border-left: 3px solid var(--accent);
  margin: 0.5em 0;
  padding: 0.3em 0.8em;
  color: var(--text);
  background: rgba(167, 139, 250, 0.06);
  border-radius: 0 4px 4px 0;
}

.message.agent .bubble :deep(code) {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-h);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace;
}
.message.agent .bubble :deep(pre) {
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0.5em 0;
}
.message.agent .bubble :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
  font-size: 0.85em;
}

.message.agent .bubble :deep(ul),
.message.agent .bubble :deep(ol) {
  margin: 0.4em 0;
  padding-left: 1.5em;
}
.message.agent .bubble :deep(li) {
  margin: 0.2em 0;
}

.message.agent .bubble :deep(hr) {
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  margin: 0.8em 0;
}

.message.agent .bubble :deep(a) {
  color: var(--accent);
  text-decoration: none;
}
.message.agent .bubble :deep(a:hover) {
  text-decoration: underline;
}

.thinking {
  color: var(--text-dim);
  font-style: italic;
}

/* 高亮动画 */
.bubble.highlighted {
  animation: answerHighlight 2s ease;
}

@keyframes answerHighlight {
  0% {
    background: rgba(255, 255, 255, 0.06);
    transform: scale(1);
    box-shadow: none;
  }
  15% {
    transform: scale(1.03);
  }
  30% {
    transform: scale(1);
  }
  10%, 20%, 30%, 40%, 50% {
    background: rgba(167, 139, 250, 0.18);
    box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.35), 0 0 24px rgba(167, 139, 250, 0.25);
  }
  100% {
    background: rgba(255, 255, 255, 0.06);
    transform: scale(1);
    box-shadow: none;
  }
}

.greeting {
  animation: fadeIn 0.5s ease;
}

.greeting-bubble {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border-bottom-left-radius: 4px;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 回到底部按钮 */
.back-to-bottom {
  position: absolute;
  bottom: 70px;
  right: 16px;
  padding: 6px 12px;
  background: var(--panel-bg);
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: 20px;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.4);
  z-index: 10;
  transition: all 0.2s;
}

.back-to-bottom:hover {
  background: rgba(167, 139, 250, 0.15);
}

.mobile-arrow { display: none; }
.pc-text { display: inline; }

.input-area {
  padding: 12px 16px;
  border-top: 1px solid var(--panel-border);
  display: flex;
  gap: 8px;
}

@media (max-width: 768px) {
  .input-area {
    padding: 10px 12px;
    gap: 6px;
  }
}

.input {
  flex: 1;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  font-size: 14px;
  color: var(--text-h);
  outline: none;
  transition: border-color 0.2s;
}

.input::placeholder {
  color: var(--text-dim);
}

.input:focus {
  border-color: var(--accent);
}

.send-btn {
  padding: 8px 16px;
  background: linear-gradient(135deg, #a78bfa 0%, #8b6ff0 100%);
  color: #fff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  box-shadow: 0 2px 12px rgba(167, 139, 250, 0.3);
}

.send-btn:disabled {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-dim);
  box-shadow: none;
  cursor: not-allowed;
}

/* ═══ 手机端响应式适配 ═══ */
@media (max-width: 767px) {
  .chat-panel {
    border-right: none;
    box-shadow: none;
  }

  .messages {
    padding: 10px;
    gap: 10px;
  }

  .message {
    gap: 6px;
  }

  .avatar {
    font-size: 20px;
  }

  .greeting-avatar,
  .bot-avatar {
    filter: drop-shadow(0 0 4px rgba(167, 139, 250, 0.3));
  }

  .bot-avatar {
    transform: scale(0.85);
  }

  .bubble {
    font-size: 15px;
    padding: 11px 15px;
    max-width: 92%;
  }

  .back-to-bottom {
    bottom: 65px;
    right: 12px;
    padding: 6px 10px;
    font-size: 14px;
  }
  .mobile-arrow { display: inline; }
  .pc-text { display: none; }

  .input-area {
    padding: 10px;
    gap: 8px;
    flex-wrap: wrap;
  }

  .input {
    font-size: 16px; /* 防止 iOS 缩放 */
    padding: 10px 14px;
    min-width: 0;
    flex: 1 1 auto;
  }

  .send-btn {
    padding: 10px 20px;
    font-size: 15px;
    flex-shrink: 0;
  }
}
</style>
