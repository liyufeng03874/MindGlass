<template>
  <div class="chat-panel" :style="{ '--phase-border': phaseBorderColor }">
    <div class="messages" ref="messagesRef" @scroll="handleScroll">
      <!-- 开场白 -->
      <div v-if="displayItems.length === 0 && initialGreeting" class="message agent greeting">
        <div class="avatar greeting-avatar"><MirrorIcon :size="26" /></div>
        <div class="bubble greeting-bubble">{{ initialGreeting }}</div>
      </div>

      <!-- ═══ 统一渲染循环：用户问题 → 思考直播 blocks → 最终回答 ═══ -->
      <template v-for="item in displayItems" :key="item.id">
        <!-- 消息气泡（用户问题 / 最终回答） -->
        <div v-if="item.kind === 'message'" :class="['message', item.role]">
          <div class="avatar">{{ item.role === 'user' ? '👤' : '🤖' }}</div>
          <div
            class="bubble"
            v-if="item.role === 'agent'"
            v-html="md.render(item.content ?? '')"
            :class="{ highlighted: item._isLastAgent }"
          ></div>
          <div class="bubble" v-else>{{ item.content ?? '' }}</div>
        </div>

        <!-- 思考直播 blocks（仅在有数据时渲染，不留空白区） -->
        <template v-if="item.kind === 'thought'">
          <!-- 将连续的 toolcall block 分组为并行组（同 parallelGroupId） -->
          <template v-for="blockGroup in blockGroups" :key="'bg-' + blockGroup.groupId">
            <!-- 单列 block（plan/observe/answer 或孤立 toolcall） -->
            <div
              v-if="blockGroup.single"
              :class="['thought-block', `thought-${blockGroup.single.type}`]"
            >
              <!-- 标题行 -->
              <div class="thought-header">
                <span class="thought-title" :class="{ 'is-loading': blockGroup.single.status === 'loading' }">
                  {{ blockGroup.single.title }}
                  <span v-if="blockGroup.single.status === 'loading'" class="pulse-dot" />
                </span>
                <!-- ToolCall 展开/收起按钮 -->
                <button
                  v-if="blockGroup.single.type === 'toolcall' && (blockGroup.single.metadata?.resultPreview ?? '') !== ''"
                  class="expand-btn"
                  @click="toggleExpand(blockGroup.single.id)"
                >
                  {{ expandedBlocks[blockGroup.single.id] ? '收起' : '展开' }}
                </button>
              </div>
              <!-- 内容区 -->
              <div
                class="thought-content"
                :class="{
                  'is-loading': blockGroup.single.status === 'loading',
                  'is-collapsed': blockGroup.single.type === 'toolcall' && !expandedBlocks[blockGroup.single.id]
                }"
              >
                <!-- plan/observe/answer → markdown 渲染 -->
                <template v-if="blockGroup.single.type === 'plan' || blockGroup.single.type === 'observe' || blockGroup.single.type === 'answer'">
                  <div v-if="blockGroup.single.content" class="markdown-body" v-html="md.render(blockGroup.single.content)" />
                  <span v-else class="placeholder">等待内容...</span>
                </template>
                <!-- toolcall → 结果预览 -->
                <template v-if="blockGroup.single.type === 'toolcall'">
                  <div class="tool-params" v-if="blockGroup.single.metadata?.params">
                    <span class="tool-param-label">参数：</span>
                    <code>{{ summarizeParams(blockGroup.single.metadata.params) }}</code>
                  </div>
                  <pre class="tool-result" v-if="(blockGroup.single.metadata?.resultPreview ?? '') !== ''">{{ (blockGroup.single.metadata?.resultPreview ?? '') }}</pre>
                  <span v-else class="placeholder">无结果</span>
                </template>
              </div>
            </div>

            <!-- 并行工具组（两列 grid） -->
            <div
              v-else-if="(blockGroup.blocks?.length ?? 0) > 0"
              class="thought-block thought-toolcall-parallel"
            >
              <div class="tool-parallel-grid">
                <div
                  v-for="block in blockGroup.blocks"
                  :key="'pb-' + block.id"
                  class="thought-block thought-toolcall parallel-card"
                >
                  <div class="thought-header">
                    <span class="thought-title" :class="{ 'is-loading': block.status === 'loading' }">
                      {{ block.title }}
                      <span v-if="block.status === 'loading'" class="pulse-dot" />
                    </span>
                    <button
                      v-if="(block.metadata?.resultPreview ?? '') !== ''"
                      class="expand-btn"
                      @click="toggleExpand(block.id)"
                    >
                      {{ expandedBlocks[block.id] ? '收起' : '展开' }}
                    </button>
                  </div>
                  <div
                    class="thought-content"
                    :class="{
                      'is-loading': block.status === 'loading',
                      'is-collapsed': !expandedBlocks[block.id]
                    }"
                  >
                    <div class="tool-params" v-if="block.metadata?.params">
                      <span class="tool-param-label">参数：</span>
                      <code>{{ summarizeParams(block.metadata.params) }}</code>
                    </div>
                    <pre class="tool-result" v-if="(block.metadata?.resultPreview ?? '') !== ''">{{ (block.metadata?.resultPreview ?? '') }}</pre>
                    <span v-else class="placeholder">无结果</span>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </template>
      </template>

      <div v-if="loading" class="message agent">
        <div class="avatar">🤖</div>
        <div class="bubble thinking">{{ statusText || '正在规划...' }}</div>
      </div>
    </div>

    <!-- 回到最新按钮 -->
    <button v-if="showBackToBottom" class="back-to-bottom" @click="scrollToBottom">
      ↓ 回到最新
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
import { ref, watch, nextTick, computed } from 'vue'
import MarkdownIt from 'markdown-it'
import type { LeftBlock } from '../types/agent'
import MirrorIcon from './MirrorIcon.vue'
import { usePhase, phaseColor } from '../composables/usePhase'

const md = new MarkdownIt({ breaks: true, linkify: true })

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
  messages: Array<{ role: 'user' | 'agent', content: string }>
  disabled?: boolean
  initialGreeting?: string
  statusText?: string
  totalElapsed?: string | null
  leftBlocks?: LeftBlock[]
}>()

const emit = defineEmits<{
  send: [query: string]
}>()

const inputValue = ref('')
const highlightIndex = ref<number | null>(null)
const messagesRef = ref<HTMLElement | null>(null)
const loading = computed(() => props.disabled)

// 水镜：左侧跟随右侧相位呼吸
const { phase } = usePhase()
const phaseBorderColor = computed(() => phaseColor(phase.value))

// ── 自动滚动：检测用户是否在底部 ──
const showBackToBottom = ref(false)
const isNearBottom = ref(true)

/** 滚动到最底部 */
function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

/** 判断是否接近底部（阈值 60px） */
function isAtBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 60
}

function handleScroll() {
  if (messagesRef.value) {
    isNearBottom.value = isAtBottom(messagesRef.value)
    showBackToBottom.value = !isNearBottom.value
  }
}

// 新 block/chunk 到来时，若用户贴底则自动滚到底
watch(
  () => props.leftBlocks?.length,
  () => {
    nextTick(() => {
      if (isNearBottom.value && messagesRef.value) {
        messagesRef.value.scrollTop = messagesRef.value.scrollHeight
      }
    })
  },
  { deep: true }
)

// 新消息到来时也自动滚
watch(() => props.messages.length, async () => {
  await nextTick()
  if (messagesRef.value && isNearBottom.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
})

function highlightLastMessage() {
  if (messagesRef.value && props.messages.length > 0) {
    messagesRef.value.scrollTo({
      top: messagesRef.value.scrollHeight,
      behavior: 'smooth',
    })
    highlightIndex.value = props.messages.length - 1
    setTimeout(() => {
      highlightIndex.value = null
    }, 2000)
  }
}

defineExpose({ highlightLastMessage })

function handleSend() {
  const query = inputValue.value.trim()
  if (!query) return
  emit('send', query)
  inputValue.value = ''
}

// ── 工具参数摘要 ──
function summarizeParams(params: Record<string, any>): string {
  if (!params) return ''
  const parts: string[] = []
  if (params.query) parts.push(`query="${params.query}"`)
  if (params.top_k) parts.push(`top_k=${params.top_k}`)
  const keys = Object.keys(params).filter(k => !['query', 'top_k'].includes(k))
  for (const k of keys.slice(0, 2)) {
    parts.push(`${k}="${params[k]}"`)
  }
  return parts.join(', ') || JSON.stringify(params)
}

// ── 工具结果展开/收起 ──
const expandedBlocks = ref<Record<string, boolean>>({})

function toggleExpand(blockId: string) {
  expandedBlocks.value[blockId] = !expandedBlocks.value[blockId]
}

// ── Block 分组：连续 toolcall 聚合为并行组 ──
// 聚合规则：相邻且类型都是 'toolcall' 且都有 parallelGroupId 的 block 归为一组；
// 孤立的 toolcall 或不同类型的 block 作为 single 输出。
interface BlockGroup {
  groupId: string
  single?: LeftBlock
  blocks?: LeftBlock[]
}

const blockGroups = computed<BlockGroup[]>(() => {
  const blocks = props.leftBlocks || []
  const groups: BlockGroup[] = []
  let i = 0
  while (i < blocks.length) {
    const b = blocks[i]
    // 检查是否是并行 toolcall 组的开始
    if (b.type === 'toolcall' && b.parallelGroupId) {
      const pgId = b.parallelGroupId!
      const groupBlocks: LeftBlock[] = []
      while (i < blocks.length && blocks[i].type === 'toolcall' && blocks[i].parallelGroupId === pgId) {
        groupBlocks.push(blocks[i])
        i++
      }
      if (groupBlocks.length > 1) {
        groups.push({ groupId: `parallel_${pgId}`, blocks: groupBlocks })
      } else {
        groups.push({ groupId: `single_${groupBlocks[0].id}`, single: groupBlocks[0] })
      }
    } else {
      groups.push({ groupId: `single_${b.id}`, single: b })
      i++
    }
  }
  return groups
})

/** ═══ 统一渲染列表：用户问题 → 思考直播 blocks → 最终回答 ═══
 *  保证一次 run 内顺序 = 用户气泡 → 思考 blocks → 最终回答气泡
 *  demo 加载场景 leftBlocks 为空时不留空白区
 */
interface DisplayItem {
  id: string
  kind: 'message' | 'thought'
  role?: 'user' | 'agent'
  content?: string
  _isLastAgent?: boolean
}

const displayItems = computed<DisplayItem[]>(() => {
  const items: DisplayItem[] = []
  const msgs = props.messages
  const blocks = props.leftBlocks || []
  const hasBlocks = blocks.length > 0

  // 标记：思考 blocks 是否已渲染（一次 run 只渲染一次）
  let thoughtRendered = false

  for (let i = 0; i < msgs.length; i++) {
    const msg = msgs[i]
    let content = msg.content

    // 将总用时追加到最后一条 agent 消息末尾
    if (msg.role === 'agent' && props.totalElapsed) {
      const lastAgentIdx = [...msgs].reverse().findIndex(m => m.role === 'agent')
      if (i === msgs.length - 1 - lastAgentIdx) {
        content += `\n\n---\n\n*（本次推理耗时 ${props.totalElapsed}）*`
      }
    }

    items.push({
      id: `msg-${i}`,
      kind: 'message',
      role: msg.role,
      content,
    })

    // 在用户消息之后插入思考 blocks（仅一次）
    if (msg.role === 'user' && hasBlocks && !thoughtRendered) {
      items.push({
        id: 'thought-blocks',
        kind: 'thought',
      })
      thoughtRendered = true
    }
  }

  // 边界：没有 messages 但有 leftBlocks（极少见，兜底渲染）
  if (!thoughtRendered && hasBlocks) {
    items.push({ id: 'thought-blocks', kind: 'thought' })
  }

  // 标记最后一条 agent 消息用于高亮
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].role === 'agent') {
      items[i]._isLastAgent = true
      break
    }
  }

  return items
})
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
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
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

.bubble {
  text-align: left;
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
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

.elapsed-badge {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-dim);
  font-size: 12px;
  font-family: 'Menlo', 'Monaco', monospace;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--panel-border);
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

/* ═══ 思考直播区样式 ═══ */

.thought-block {
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  overflow: hidden;
}

/* 不同类型左边框颜色区分 */
.thought-plan {
  border-left: 3px solid #a78bfa;
}
.thought-toolcall {
  border-left: 3px solid #f59e0b;
}
.thought-observe {
  border-left: 3px solid #10b981;
}
.thought-answer {
  border-left: 3px solid #3b82f6;
}

.thought-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.04);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.thought-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-h);
  display: flex;
  align-items: center;
  gap: 6px;
}

/* Loading 脉冲动画 */
.thought-title.is-loading {
  animation: pulseText 1.5s ease-in-out infinite;
}

@keyframes pulseText {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.pulse-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: pulseDot 1.5s ease-in-out infinite;
}

@keyframes pulseDot {
  0%, 100% {
    opacity: 1;
    box-shadow: 0 0 4px var(--accent);
  }
  50% {
    opacity: 0.4;
    box-shadow: 0 0 12px var(--accent);
  }
}

.expand-btn {
  font-size: 11px;
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--panel-border);
  border-radius: 4px;
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.2s;
}

.expand-btn:hover {
  background: rgba(167, 139, 250, 0.15);
  color: var(--text-h);
}

.thought-content {
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
}

/* Loading 状态：底部呼吸边框 */
.thought-content.is-loading {
  position: relative;
  animation: loadingPulse 2s ease-in-out infinite;
}

@keyframes loadingPulse {
  0%, 100% {
    border-bottom: 1px solid transparent;
  }
  50% {
    border-bottom: 1px solid rgba(167, 139, 250, 0.3);
  }
}

/* Markdown 渲染区域 */
.thought-content :deep(h1),
.thought-content :deep(h2),
.thought-content :deep(h3) {
  margin: 0.6em 0 0.3em;
  font-weight: 600;
  line-height: 1.3;
}
.thought-content :deep(h1) { font-size: 1.15em; }
.thought-content :deep(h2) { font-size: 1.05em; }
.thought-content :deep(p) { margin: 0.3em 0; }
.thought-content :deep(code) {
  background: rgba(255, 255, 255, 0.08);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.9em;
  font-family: 'Fira Code', Consolas, monospace;
}
.thought-content :deep(pre) {
  background: #1e1e2e;
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 0.4em 0;
}
.thought-content :deep(pre code) {
  background: none;
  padding: 0;
}
.thought-content :deep(ul),
.thought-content :deep(ol) {
  margin: 0.3em 0;
  padding-left: 1.5em;
}
.thought-content :deep(li) { margin: 0.15em 0; }

/* 工具参数行 */
.tool-params {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 6px;
}
.tool-params code {
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 5px;
  border-radius: 3px;
  font-family: 'Fira Code', Consolas, monospace;
  font-size: 0.95em;
}

/* 工具结果区：默认限高 200px，可展开 */
.tool-result {
  background: #1a1a2e;
  color: #cdd6f4;
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  font-family: 'Fira Code', Consolas, monospace;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  overflow-y: auto;
  max-height: 200px;
}

/* 折叠状态：限高 200px */
.thought-content.is-collapsed .tool-result {
  max-height: 200px;
}

/* 展开状态：不限高 */
.thought-content:not(.is-collapsed) .tool-result {
  max-height: none;
}

.placeholder {
  color: var(--text-dim);
  font-style: italic;
  font-size: 12px;
}

/* 并行工具组网格 */
.tool-parallel-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 8px;
}

.parallel-card {
  margin: 0;
}

.parallel-card .thought-content {
  font-size: 12px;
}

/* 回到最新按钮 */
.back-to-bottom {
  position: absolute;
  bottom: 70px;
  left: 50%;
  transform: translateX(-50%);
  padding: 6px 16px;
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

.input-area {
  padding: 12px 16px;
  border-top: 1px solid var(--panel-border);
  display: flex;
  gap: 8px;
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
</style>
