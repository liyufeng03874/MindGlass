<template>
  <div class="chat-panel" :style="{ '--phase-border': phaseBorderColor }">
    <div class="messages" ref="messagesRef" @scroll="handleScroll">
      <!-- 开场白 -->
      <div v-if="(displayItems?.length ?? 0) === 0 && initialGreeting" class="message agent greeting">
        <div class="avatar greeting-avatar"><MirrorIcon :size="26" /></div>
        <div class="bubble greeting-bubble">{{ initialGreeting }}</div>
      </div>

      <!-- ═══ 统一渲染循环：用户问题 → 思考直播 blocks → 最终回答 ═══ -->
      <template v-for="item in displayItems" :key="item.id">
        <!-- 消息气泡（用户问题 / 最终回答） -->
        <div v-if="item.kind === 'message'" :class="['message', item.role]">
          <div class="avatar" v-if="item.role === 'user'">👤</div>
          <div class="avatar bot-avatar" v-else><MirrorIcon :size="24" /></div>
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
            <!-- 分割线 block（打断/重试分支的边界） -->
            <div v-if="blockGroup.single && blockGroup.single.type === 'divider'" class="phase-divider">
              <span class="divider-label">{{ blockGroup.single.title }}</span>
            </div>
            <!-- 单列 block（plan/observe/answer 或孤立 toolcall） -->
            <div
              v-else-if="blockGroup.single"
              :data-block-id="blockGroup.single.id"
              :class="['thought-block', `thought-${blockGroup.single.type}`, { 'phase-cut': blockGroup.single.phase === 'cut', 'phase-retry': blockGroup.single.phase === 'retry' }]"
            >
              <!-- 标题行 -->
              <div class="thought-header">
                <span class="thought-title" :class="{ 'is-loading': blockGroup.single.status === 'loading' }">
                  {{ blockGroup.single.title }}
                  <span v-if="blockGroup.single.status === 'loading'" class="pulse-dot" />
                </span>
                <!-- ToolCall 展开/收起按钮 -->
                <button
                  v-if="blockGroup.single.type === 'toolcall' && getToolRawText(blockGroup.single) !== ''"
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
                <!-- plan/observe/answer → 完成后尝试人读视图；流式中或解析失败回退原文 -->
                <template v-if="blockGroup.single.type === 'plan' || blockGroup.single.type === 'observe' || blockGroup.single.type === 'answer'">
                  <!-- 非最终回答的 plan/observe：完成后显示人读视图 -->
                  <template v-if="blockGroup.single.type !== 'answer' && blockGroup.single.status === 'done'">
                    <div v-if="parsedBlockContent(blockGroup.single)" class="readable-content">
                      <!-- 人读结构化视图 -->
                      <template v-if="parsedBlockContent(blockGroup.single)?.type === 'plan'">
                        <div class="readable-section">
                          <div class="readable-label">💭 思考</div>
                          <div class="readable-text">{{ parsedBlockContent(blockGroup.single)?.thought || parsedBlockContent(blockGroup.single)?.reasoning || '' }}</div>
                        </div>
                        <div v-if="parsedBlockContent(blockGroup.single)?.steps?.length" class="readable-section">
                          <div class="readable-label">📋 步骤</div>
                          <ol class="readable-steps">
                            <li v-for="(s, si) in parsedBlockContent(blockGroup.single)?.steps" :key="si">
                              <span class="step-badge">{{ toolLabel(s.tool) }}</span>
                              <span class="step-desc">{{ s.description || '' }}</span>
                              <span v-if="s.params?.query" class="step-query">query: "{{ s.params.query }}"</span>
                            </li>
                          </ol>
                        </div>
                        <div v-if="parsedBlockContent(blockGroup.single)?.decision && planRound(blockGroup.single) > 1" class="readable-section">
                          <div class="readable-label">🎯 决策</div>
                          <span class="decision-badge" :class="`decision-${getDecision(blockGroup.single)}`">
                            {{ getDecisionLabel(blockGroup.single) }}
                          </span>
                        </div>
                      </template>
                      <template v-else-if="parsedBlockContent(blockGroup.single)?.type === 'observe'">
                        <div v-if="parsedBlockContent(blockGroup.single)?.summary" class="readable-section">
                          <div class="readable-label">📝 摘要</div>
                          <div class="readable-text">{{ parsedBlockContent(blockGroup.single)?.summary }}</div>
                        </div>
                        <div v-if="parsedBlockContent(blockGroup.single)?.key_findings?.length" class="readable-section">
                          <div class="readable-label">🔑 要点</div>
                          <ul class="readable-list">
                            <li v-for="(f, fi) in parsedBlockContent(blockGroup.single)?.key_findings" :key="fi">{{ f }}</li>
                          </ul>
                        </div>
                        <div v-if="parsedBlockContent(blockGroup.single)?.conflicts?.length" class="readable-section">
                          <div class="readable-label">⚠️ 矛盾</div>
                          <ul class="readable-list conflict-list">
                            <li v-for="(c, ci) in parsedBlockContent(blockGroup.single)?.conflicts" :key="ci">
                              <strong>{{ c.topic || '矛盾' }}</strong>：{{ c.resolution || '' }}
                              <span v-if="c.confidence" class="confidence">（置信度: {{ c.confidence }}）</span>
                            </li>
                          </ul>
                        </div>
                        <div v-if="parsedBlockContent(blockGroup.single)?.new_info_vs_previous && (parsedBlockContent(blockGroup.single)?.round ?? 0) > 1" class="readable-section">
                          <div class="readable-label">🆕 新增信息</div>
                          <div class="readable-text">{{ parsedBlockContent(blockGroup.single)?.new_info_vs_previous }}</div>
                        </div>
                      </template>
                      <!-- 查看原文按钮 -->
                      <button class="toggle-raw-btn" @click="toggleRaw(blockGroup.single.id)">
                        {{ showRaw[blockGroup.single.id] ? '收起原文' : '查看原文' }}
                      </button>
                      <!-- 原始 JSON（默认折叠） -->
                      <pre v-if="showRaw[blockGroup.single.id] && formattedJson(blockGroup.single.content)" class="json-body">{{ formattedJson(blockGroup.single.content) }}</pre>
                    </div>
                    <!-- 流式中或解析失败：回退原文 -->
                    <template v-else>
                      <pre v-if="formattedJson(blockGroup.single.content)" class="json-body">{{ formattedJson(blockGroup.single.content) }}</pre>
                      <div v-else-if="blockGroup.single.content" class="markdown-body" v-html="md.render(blockGroup.single.content)" />
                      <span v-else class="placeholder">等待内容...</span>
                    </template>
                  </template>
                  <!-- 最终回答 answer：保持 markdown 渲染 -->
                  <template v-else>
                    <div v-if="blockGroup.single.content" class="markdown-body" v-html="md.render(blockGroup.single.content)" />
                    <span v-else class="placeholder">等待内容...</span>
                  </template>
                </template>
                <!-- toolcall → 人读视图（搜索结果列表）+ 查看原文 -->
                <template v-if="blockGroup.single.type === 'toolcall'">
                  <div class="tool-params" v-if="blockGroup.single.metadata?.params">
                    <span class="tool-param-label">参数：</span>
                    <code>{{ summarizeParams(blockGroup.single.metadata.params) }}</code>
                  </div>
                  <!-- 人读视图：解析 resultFull（回退 resultPreview） -->
                  <template v-if="parsedToolResult(blockGroup.single)">
                    <!-- 搜索结果列表 -->
                    <template v-if="parsedToolResult(blockGroup.single)?.type === 'search_ok'">
                      <div class="tool-results-readable">
                        <div v-for="(r, ri) in parsedToolResult(blockGroup.single)?.items" :key="ri" class="result-item" :class="{ 'item-hidden': !expandedBlocks[blockGroup.single.id] && ri >= 3 }">
                          <a v-if="r.url" :href="r.url" target="_blank" rel="noopener noreferrer" class="result-title">{{ r.title }}</a>
                          <span v-else class="result-title">{{ r.title }}</span>
                          <span v-if="r.url" class="result-domain">{{ extractDomain(r.url) }}</span>
                          <p class="result-snippet">{{ r.snippet }}</p>
                        </div>
                      </div>
                      <button v-if="(parsedToolResult(blockGroup.single)?.items?.length ?? 0) > 3" class="expand-all-btn" @click="toggleExpand(blockGroup.single.id)">
                        {{ expandedBlocks[blockGroup.single.id] ? '收起' : `展开全部 ${parsedToolResult(blockGroup.single)?.items?.length} 条` }}
                      </button>
                    </template>
                    <!-- 工具返回了 error -->
                    <template v-else-if="parsedToolResult(blockGroup.single)?.type === 'error'">
                      <div class="tool-error-msg">⚠️ {{ parsedToolResult(blockGroup.single)?.message || '工具返回错误' }}</div>
                    </template>
                    <!-- 结果为空 -->
                    <template v-else>
                      <span class="placeholder">无结果</span>
                    </template>
                  </template>
                  <!-- 解析失败/未完成：回退原文 -->
                  <template v-else>
                    <pre class="tool-result" v-if="getToolRawText(blockGroup.single) !== ''">{{ getToolRawText(blockGroup.single) }}</pre>
                    <span v-else-if="blockGroup.single.status === 'done'" class="placeholder">无结果</span>
                    <span v-else class="placeholder">等待结果...</span>
                  </template>
                  <!-- 查看原文按钮（仅当有人读视图时显示） -->
                  <button v-if="parsedToolResult(blockGroup.single)" class="toggle-raw-btn" @click="toggleRaw(blockGroup.single.id)">
                    {{ showRaw[blockGroup.single.id] ? '收起原文' : '查看原文' }}
                  </button>
                  <pre v-if="showRaw[blockGroup.single.id] && formattedToolJson(blockGroup.single)" class="json-body">{{ formattedToolJson(blockGroup.single) }}</pre>
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
                      v-if="getToolRawText(block) !== ''"
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
                    <!-- 人读视图：解析 resultFull（回退 resultPreview） -->
                    <template v-if="parsedToolResult(block)">
                      <template v-if="parsedToolResult(block)?.type === 'search_ok'">
                        <div class="tool-results-readable">
                          <div v-for="(r, ri) in parsedToolResult(block)?.items" :key="ri" class="result-item" :class="{ 'item-hidden': !expandedBlocks[block.id] && ri >= 3 }">
                            <a v-if="r.url" :href="r.url" target="_blank" rel="noopener noreferrer" class="result-title">{{ r.title }}</a>
                            <span v-else class="result-title">{{ r.title }}</span>
                            <span v-if="r.url" class="result-domain">{{ extractDomain(r.url) }}</span>
                            <p class="result-snippet">{{ r.snippet }}</p>
                          </div>
                        </div>
                        <button v-if="(parsedToolResult(block)?.items?.length ?? 0) > 3" class="expand-all-btn" @click="toggleExpand(block.id)">
                          {{ expandedBlocks[block.id] ? '收起' : `展开全部 ${parsedToolResult(block)?.items?.length} 条` }}
                        </button>
                      </template>
                      <template v-else-if="parsedToolResult(block)?.type === 'error'">
                        <div class="tool-error-msg">⚠️ {{ parsedToolResult(block)?.message || '工具返回错误' }}</div>
                      </template>
                      <template v-else>
                        <span class="placeholder">无结果</span>
                      </template>
                    </template>
                    <!-- 解析失败/未完成：回退原文 -->
                    <template v-else>
                      <pre class="tool-result" v-if="getToolRawText(block) !== ''">{{ getToolRawText(block) }}</pre>
                      <span v-else-if="block.status === 'done'" class="placeholder">无结果</span>
                      <span v-else class="placeholder">等待结果...</span>
                    </template>
                    <button v-if="parsedToolResult(block)" class="toggle-raw-btn" @click="toggleRaw(block.id)">
                      {{ showRaw[block.id] ? '收起原文' : '查看原文' }}
                    </button>
                    <pre v-if="showRaw[block.id] && formattedToolJson(block)" class="json-body">{{ formattedToolJson(block) }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </template>
      </template>

      <div v-if="loading" class="message agent">
        <div class="avatar bot-avatar"><MirrorIcon :size="24" /></div>
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

/**
 * 任务⑦ T2：聚焦到左侧思考直播区最后一个 answer block，播放聚焦动画
 * 与完成时的 answerHighlight 动画视觉一致，可重复触发
 */
function highlightLastAnswerBlock() {
  // 找最后一个 type=answer 的 block
  const blocks = props.leftBlocks || []
  const lastAnswerIdx = [...blocks].reverse().findIndex(b => b.type === 'answer')
  if (lastAnswerIdx < 0) {
    // 兜底：没有 answer block 则用旧逻辑
    highlightLastMessage()
    return
  }
  // 正向 index
  const answerIdx = blocks.length - 1 - lastAnswerIdx

  // 滚动到最底（answer block 一般在底部）
  if (messagesRef.value) {
    messagesRef.value.scrollTo({
      top: messagesRef.value.scrollHeight,
      behavior: 'smooth',
    })
  }

  // 对 answer block 播放聚焦动画：通过 CSS class 触发
  // 使用 blockId 来标记动画，支持重复触发（先移除再添加，强制重绘）
  const blockId = blocks[answerIdx].id
  // 用 DOM 查找该 block 元素
  nextTick(() => {
    const el = document.querySelector(`[data-block-id="${blockId}"] .thought-content`)
    if (el) {
      // 先移除旧动画类，强制浏览器重绘后再添加，确保每次点击都能重新触发动画
      el.classList.remove('answer-block-highlight')
      void el.offsetWidth  // 强制重绘（reflow）
      el.classList.add('answer-block-highlight')
      setTimeout(() => {
        el.classList.remove('answer-block-highlight')
      }, 2000)
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

// ── JSON 格式化展示（plan/observe 内容能解析成 JSON 就美化展示）──
function formattedJson(content: string): string | null {
  if (!content) return null
  let src = content.trim()
  // 去 markdown 代码围栏
  if (src.startsWith('```')) {
    src = src.split('\n').slice(1).join('\n')
    const idx = src.lastIndexOf('```')
    if (idx >= 0) src = src.slice(0, idx)
    src = src.trim()
  }
  const start = src.indexOf('{')
  const end = src.lastIndexOf('}')
  if (start < 0 || end <= start) return null
  try {
    return JSON.stringify(JSON.parse(src.slice(start, end + 1)), null, 2)
  } catch {
    return null  // 流式中 JSON 未完成时解析失败，保持原文显示
  }
}

// ── 工具结果人读视图解析器（任务⑦：单列/并行组共用）
interface ParsedToolResult {
  type: 'search_ok' | 'error' | 'empty'
  items?: Array<{ title: string; url: string; snippet: string }>
  message?: string
}

function parsedToolResult(block: LeftBlock): ParsedToolResult | null {
  // 未完成状态不解析
  if (block.status !== 'done') return null

  // 优先 resultFull，回退 resultPreview
  const raw = block.metadata?.resultFull || block.metadata?.resultPreview || ''
  if (!raw) return null

  // 解析 JSON
  let obj: any
  try {
    obj = JSON.parse(raw)
  } catch {
    return null
  }

  // 解包 execute_tool 的外层包装 {tool, params, result}——工具真实返回值在 result 里
  const inner =
    obj && typeof obj === 'object' && !Array.isArray(obj) &&
    obj.result && typeof obj.result === 'object' && !Array.isArray(obj.result)
      ? obj.result
      : obj

  // 错误情况（外层 error 或内层 error）
  if (obj.error || inner.error) {
    return { type: 'error', message: inner.error || obj.error }
  }

  // 结果数组：search → results；rag_retrieve → passages
  const arr = Array.isArray(inner.results)
    ? inner.results
    : Array.isArray(inner.passages) ? inner.passages : null
  if (!arr) return null
  if (arr.length === 0) return { type: 'empty' }
  const items = arr
    .filter((r: any) => r && (r.title || r.url || r.snippet || r.content || r.text))
    .map((r: any) => ({
      title: r.title || r.name || r.source || '无标题',
      url: r.url || '',
      snippet: r.snippet || r.content || r.text || '',
    }))
  if (items.length === 0) return { type: 'empty' }
  return { type: 'search_ok', items }
}

// ── 工具结果原始文本（用于回退展示，优先 resultFull，回退 resultPreview）──
function getToolRawText(block: LeftBlock): string {
  const full = block.metadata?.resultFull || ''
  const preview = block.metadata?.resultPreview || ''
  return full || preview || ''
}

// ── 工具结果 JSON 格式化（用于查看原文）──
function formattedToolJson(block: LeftBlock): string | null {
  const raw = block.metadata?.resultFull || block.metadata?.resultPreview || ''
  if (!raw) return null
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return null
  }
}

// ── 提取域名 ──
function extractDomain(url: string): string {
  try {
    const u = new URL(url)
    return u.hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
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

// ── 查看原文折叠/展开 ──
const showRaw = ref<Record<string, boolean>>({})

function toggleRaw(blockId: string) {
  showRaw.value[blockId] = !showRaw.value[blockId]
}

// ── 决策标签中文映射 ──
const decisionLabels: Record<string, string> = {
  sufficient: '✅ 信息充足',
  need_more: '🔍 需要补搜',
  terminate: '⚠️ 强制终止',
}

// ── 工具中文名映射 ──
function toolLabel(tool: string): string {
  const map: Record<string, string> = { search: '网络搜索', rag_retrieve: 'RAG 检索' }
  return map[tool] || tool
}

/**
 * 人读视图解析器：从 block content 中提取关键字段
 * 返回 null 表示无法解析（回退原文展示）
 */
interface ParsedContent {
  type: 'plan' | 'observe'
  thought?: string
  reasoning?: string
  steps?: Array<{ tool: string; description: string; params?: Record<string, any> }>
  decision?: string
  summary?: string
  key_findings?: string[]
  conflicts?: Array<{ topic: string; resolution?: string; confidence?: string }>
  new_info_vs_previous?: string
  round?: number
}

function parsedBlockContent(block: LeftBlock): ParsedContent | null {
  // 只有完成状态的 plan/observe 才做人读解析
  if (block.status !== 'done') return null
  if (!block.content) return null

  let src = block.content.trim()
  // 去 markdown 代码围栏
  if (src.startsWith('```')) {
    src = src.split('\n').slice(1).join('\n')
    const idx = src.lastIndexOf('```')
    if (idx >= 0) src = src.slice(0, idx)
    src = src.trim()
  }
  const start = src.indexOf('{')
  const end = src.lastIndexOf('}')
  if (start < 0 || end <= start) return null

  try {
    const obj = JSON.parse(src.slice(start, end + 1))
    if (block.type === 'plan') {
      return {
        type: 'plan',
        thought: obj.thought || obj.reasoning || '',
        reasoning: obj.reasoning || obj.thought || '',
        steps: Array.isArray(obj.steps) ? obj.steps : [],
        decision: obj.decision || '',
      }
    }
    if (block.type === 'observe') {
      return {
        type: 'observe',
        summary: obj.summary || '',
        key_findings: Array.isArray(obj.key_findings) ? obj.key_findings : [],
        conflicts: Array.isArray(obj.conflicts) ? obj.conflicts : [],
        new_info_vs_previous: obj.new_info_vs_previous || '',
        round: obj.round || 0,
      }
    }
    return null
  } catch {
    return null  // 解析失败，回退原文
  }
}

// ── 决策标签安全获取 ──
function getDecision(block: LeftBlock): string {
  const parsed = parsedBlockContent(block)
  return parsed?.decision || ''
}

function planRound(block: LeftBlock): number {
  const plans = (props.leftBlocks || []).filter(b => b.type === 'plan')
  return plans.findIndex(b => b.id === block.id) + 1
}

function getDecisionLabel(block: LeftBlock): string {
  const d = getDecision(block)
  // 措辞与图一致：第 2 轮（首次决策）叫"信息不足"，第 3 轮起才叫"需要补搜"（问题1）
  if (d === 'need_more') {
    return planRound(block) >= 3 ? '🔍 需要补搜' : '❓ 信息不足'
  }
  return decisionLabels[d] || d
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
  const allBlocks = props.leftBlocks || []
  const hasAgentMessage = props.messages.some(m => m.role === 'agent')
  // 若已有 agent 消息气泡，过滤掉 answer block 避免重复渲染
  // answer 最终由 agent message bubble 展示
  const blocks = hasAgentMessage
    ? allBlocks.filter(b => b.type !== 'answer')
    : allBlocks
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
  min-height: 0;  /* 关键：flex 子项才能被压缩到小于内容高度，overflow 才能生效 */
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
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
  display: flex;           /* 内部纵向排布 */
  flex-direction: column;
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

/* 任务⑦ T2：answer block 聚焦动画（与 answerHighlight 视觉一致） */
.answer-block-highlight {
  animation: answerBlockHighlight 2s ease;
}

@keyframes answerBlockHighlight {
  0% {
    background: rgba(255, 255, 255, 0.03);
    box-shadow: none;
  }
  15%, 50% {
    background: rgba(167, 139, 250, 0.15);
    box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.3), 0 0 24px rgba(167, 139, 250, 0.2);
  }
  100% {
    background: rgba(255, 255, 255, 0.03);
    box-shadow: none;
  }
}

/* ═══ 任务⑦：工具结果人读视图样式 ═══ */

.tool-results-readable {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 4px;
}

.result-item {
  padding: 8px 10px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  transition: background 0.2s;
  max-height: 120px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(167, 139, 250, 0.35) rgba(255, 255, 255, 0.04);
}
.result-item::-webkit-scrollbar {
  width: 6px;
}
.result-item::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 3px;
}
.result-item::-webkit-scrollbar-thumb {
  background: rgba(167, 139, 250, 0.35);
  border-radius: 3px;
}
.result-item::-webkit-scrollbar-thumb:hover {
  background: rgba(167, 139, 250, 0.6);
}

.result-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

/* 超过 3 条默认隐藏 */
.result-item.item-hidden {
  display: none;
}

.result-title {
  display: inline-block;
  color: #60a5fa;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  margin-right: 8px;
}

.result-title:hover {
  text-decoration: underline;
  color: #93bbfc;
}

.result-domain {
  display: inline-block;
  font-size: 11px;
  color: var(--text-dim);
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 6px;
  border-radius: 3px;
}

.result-snippet {
  font-size: 12px;
  color: var(--text-dim);
  margin: 4px 0 0;
  line-height: 1.5;
}

/* 展开全部按钮 */
.expand-all-btn {
  align-self: flex-start;
  font-size: 12px;
  padding: 4px 12px;
  background: rgba(167, 139, 250, 0.12);
  border: 1px solid rgba(167, 139, 250, 0.3);
  border-radius: 6px;
  color: #a78bfa;
  cursor: pointer;
  transition: all 0.2s;
  margin-top: 4px;
}

.expand-all-btn:hover {
  background: rgba(167, 139, 250, 0.2);
  color: #c4b5fd;
}

/* 工具错误提示 */
.tool-error-msg {
  font-size: 13px;
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.3);
  border-radius: 6px;
  padding: 8px 12px;
  line-height: 1.5;
}

/* JSON 格式化展示区（plan/observe 完成后）*/
.json-body {
  background: rgba(10, 14, 31, 0.6);
  color: #cdd6f4;
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid rgba(167, 139, 250, 0.15);
  font-size: 12px;
  font-family: 'Fira Code', Consolas, monospace;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  overflow-y: auto;
  max-height: 320px;
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

/* ═══ P1 人读视图样式 ═══ */

.readable-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.readable-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.readable-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.5px;
}

.readable-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-h);
  margin: 0;
}

/* 步骤列表 */
.readable-steps {
  margin: 4px 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-h);
}

.readable-steps li {
  margin-bottom: 4px;
}

.step-badge {
  display: inline-block;
  background: rgba(96, 165, 250, 0.15);
  color: #60a5fa;
  border: 1px solid rgba(96, 165, 250, 0.3);
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 12px;
  font-weight: 600;
  margin-right: 6px;
}

.step-desc {
  color: var(--text);
}

.step-query {
  color: var(--text-dim);
  font-size: 12px;
  font-family: 'Fira Code', Consolas, monospace;
}

/* 决策徽章 */
.readable-decision {
  margin-top: 4px;
}

.decision-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
}

.decision-badge.sufficient {
  background: rgba(52, 211, 153, 0.15);
  color: #34d399;
  border: 1px solid rgba(52, 211, 153, 0.4);
}

.decision-badge.need_more {
  background: rgba(251, 191, 36, 0.15);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.4);
}

.decision-badge.terminate {
  background: rgba(248, 113, 113, 0.15);
  color: #f87171;
  border: 1px solid rgba(248, 113, 113, 0.4);
}

/* 要点 bullet 列表 */
.readable-list {
  margin: 4px 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-h);
}

.readable-list li {
  margin-bottom: 3px;
}

/* 矛盾列表 */
.conflict-list {
  color: var(--text-h);
}

.conflict-list strong {
  color: #fbbf24;
}

.confidence {
  color: var(--text-dim);
  font-size: 12px;
}

/* 查看原文按钮 */
.toggle-raw-btn {
  align-self: flex-start;
  font-size: 11px;
  padding: 3px 10px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid var(--panel-border);
  border-radius: 4px;
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.2s;
  margin-top: 4px;
}

.toggle-raw-btn:hover {
  background: rgba(167, 139, 250, 0.12);
  color: var(--accent);
}

/* ═══ P4 主题化滚动条 ═══ */

.themed-scroll,
.messages,
.tool-result,
.json-body,
.readable-content,
.readable-steps,
.readable-list,
.conflict-list,
.output-preview,
.output-content,
.answer-content,
.panel-body,
.deprecated-body {
  scrollbar-width: thin;
  scrollbar-color: rgba(167, 139, 250, 0.35) rgba(255, 255, 255, 0.04);
}

.themed-scroll::-webkit-scrollbar,
.messages::-webkit-scrollbar,
.tool-result::-webkit-scrollbar,
.json-body::-webkit-scrollbar,
.readable-content::-webkit-scrollbar,
.output-preview::-webkit-scrollbar,
.output-content::-webkit-scrollbar,
.answer-content::-webkit-scrollbar,
.panel-body::-webkit-scrollbar,
.deprecated-body::-webkit-scrollbar {
  width: 8px;
}

.themed-scroll::-webkit-scrollbar-track,
.messages::-webkit-scrollbar-track,
.tool-result::-webkit-scrollbar-track,
.json-body::-webkit-scrollbar-track,
.output-preview::-webkit-scrollbar-track,
.output-content::-webkit-scrollbar-track,
.answer-content::-webkit-scrollbar-track,
.panel-body::-webkit-scrollbar-track,
.deprecated-body::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 4px;
}

.themed-scroll::-webkit-scrollbar-thumb,
.messages::-webkit-scrollbar-thumb,
.tool-result::-webkit-scrollbar-thumb,
.json-body::-webkit-scrollbar-thumb,
.output-preview::-webkit-scrollbar-thumb,
.output-content::-webkit-scrollbar-thumb,
.answer-content::-webkit-scrollbar-thumb,
.panel-body::-webkit-scrollbar-thumb,
.deprecated-body::-webkit-scrollbar-thumb {
  background: rgba(167, 139, 250, 0.35);
  border-radius: 4px;
  transition: background 0.2s;
}

.themed-scroll::-webkit-scrollbar-thumb:hover,
.messages::-webkit-scrollbar-thumb:hover,
.tool-result::-webkit-scrollbar-thumb:hover,
.json-body::-webkit-scrollbar-thumb:hover,
.output-preview::-webkit-scrollbar-thumb:hover,
.output-content::-webkit-scrollbar-thumb:hover,
.answer-content::-webkit-scrollbar-thumb:hover,
.panel-body::-webkit-scrollbar-thumb:hover,
.deprecated-body::-webkit-scrollbar-thumb:hover {
  background: rgba(167, 139, 250, 0.6);
}
/* ── 分割线（打断/重试分支边界）── */
.phase-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 16px 4px 10px;
}
.phase-divider::before,
.phase-divider::after {
  content: '';
  flex: 1;
  height: 1px;
}
.phase-divider::before {
  background: linear-gradient(90deg, transparent, rgba(251, 191, 36, 0.55));
}
.phase-divider::after {
  background: linear-gradient(90deg, rgba(251, 191, 36, 0.55), transparent);
}
.divider-label {
  font-size: 12px;
  color: #fbbf24;
  letter-spacing: 2px;
  white-space: nowrap;
}

/* 被打断侧 block：整体降视觉权重 */
.thought-block.phase-cut {
  opacity: 0.55;
}
.thought-block.phase-cut .thought-title::after {
  content: ' · 被打断侧';
  color: #8a8aa0;
  font-size: 11px;
}

/* 重试分支 block：琥珀左缘标识 */
.thought-block.phase-retry {
  border-left: 2px solid rgba(251, 191, 36, 0.65);
}
.thought-block.phase-retry .thought-title::after {
  content: ' · 重试';
  color: #fbbf24;
  font-size: 11px;
}
</style>
