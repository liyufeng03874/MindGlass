<template>
  <!-- 连续的 toolcall block 分组为并行组（同 parallelGroupId） -->
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
        <!-- plan/observe/answer -->
        <template v-if="blockGroup.single.type === 'plan' || blockGroup.single.type === 'observe' || blockGroup.single.type === 'answer'">
          <!-- 非最终回答的 plan/observe：完成后显示人读视图 -->
          <template v-if="blockGroup.single.type !== 'answer' && blockGroup.single.status === 'done'">
            <div v-if="parsedBlockContent(blockGroup.single)" class="readable-content">
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
              <button class="toggle-raw-btn" @click="toggleRaw(blockGroup.single.id)">
                {{ showRaw[blockGroup.single.id] ? '收起原文' : '查看原文' }}
              </button>
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
          <template v-if="parsedToolResult(blockGroup.single)">
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
            <template v-else-if="parsedToolResult(blockGroup.single)?.type === 'error'">
              <div class="tool-error-msg">⚠️ {{ parsedToolResult(blockGroup.single)?.message || '工具返回错误' }}</div>
            </template>
            <template v-else-if="(parsedToolResult(blockGroup.single)?.type as string) === 'chatbi_sql'">
              <pre class="sql-preview">{{ parsedToolResult(blockGroup.single)?.items?.[0]?.snippet }}</pre>
            </template>
            <template v-else-if="(parsedToolResult(blockGroup.single)?.type as string) === 'chatbi_table'">
              <div class="chatbi-table-wrap" v-html="parsedToolResult(blockGroup.single)?.items?.[0]?.snippet"></div>
            </template>
            <template v-else-if="(parsedToolResult(blockGroup.single)?.type as string) === 'chatbi_chart'">
              <div :ref="(el: any) => initInlineChart(el, parsedToolResult(blockGroup.single)?.items?.[0]?.snippet)" class="inline-chart-container"></div>
            </template>
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
          :class="['thought-block', 'thought-toolcall', 'parallel-card', { 'phase-cut': block.phase === 'cut', 'phase-retry': block.phase === 'retry' }]"
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
              <template v-else-if="(parsedToolResult(block)?.type as string) === 'chatbi_sql'">
                <pre class="sql-preview">{{ parsedToolResult(block)?.items?.[0]?.snippet }}</pre>
              </template>
              <template v-else-if="(parsedToolResult(block)?.type as string) === 'chatbi_table'">
                <div class="chatbi-table-wrap" v-html="parsedToolResult(block)?.items?.[0]?.snippet"></div>
              </template>
              <template v-else-if="(parsedToolResult(block)?.type as string) === 'chatbi_chart'">
                <div :ref="(el: any) => initInlineChart(el, parsedToolResult(block)?.items?.[0]?.snippet)" class="inline-chart-container"></div>
              </template>
              <template v-else>
                <span class="placeholder">无结果</span>
              </template>
            </template>
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

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import MarkdownIt from 'markdown-it'
import type { LeftBlock } from '../types/agent'

const md = new MarkdownIt({ breaks: true, linkify: true })

const props = defineProps<{
  blocks: LeftBlock[]
}>()

// ── Block 分组：连续 toolcall 聚合为并行组 ──
interface BlockGroup {
  groupId: string
  single?: LeftBlock
  blocks?: LeftBlock[]
}

const blockGroups = computed<BlockGroup[]>(() => {
  const blocks = props.blocks || []
  const groups: BlockGroup[] = []
  let i = 0
  while (i < blocks.length) {
    const b = blocks[i]
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

// ── JSON 格式化展示 ──
function formattedJson(content: string): string | null {
  if (!content) return null
  let src = content.trim()
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
    return null
  }
}

// ── 工具结果人读视图解析器 ──
interface ParsedToolResult {
  type: 'search_ok' | 'error' | 'empty'
  items?: Array<{ title: string; url: string; snippet: string }>
  message?: string
}

function parsedToolResult(block: LeftBlock): ParsedToolResult | null {
  if (block.status !== 'done') return null
  const raw = block.metadata?.resultFull || block.metadata?.resultPreview || ''
  if (!raw) return null

  let obj: any
  try {
    obj = JSON.parse(raw)
  } catch {
    return null
  }

  // 解包 execute_tool 的外层包装 {tool, params, result}
  const inner =
    obj && typeof obj === 'object' && !Array.isArray(obj) &&
    obj.result && typeof obj.result === 'object' && !Array.isArray(obj.result)
      ? obj.result
      : obj

  if (obj.error || inner.error) {
    return { type: 'error', message: inner.error || obj.error }
  }

  // ── chatBI 工具结果解析 ──
  // 优先级：metadata.toolName(SSE直接带) > params.tool > obj.tool
  const toolName = block.metadata?.toolName || block.metadata?.params?.tool || obj.tool || ''
  if (toolName === 'gen_sql') {
    const sql = inner.sql || ''
    if (inner.error) return { type: 'error', message: inner.error }
    return { type: 'chatbi_sql' as any, items: [{ title: 'SQL', url: '', snippet: sql }] }
  }
  if (toolName === 'exec_sql') {
    if (inner.error) return { type: 'error', message: inner.error }
    const cols = inner.columns || []
    const rows = (inner.rows || []).slice(0, 10)
    let tableHtml = '<table class="chatbi-table"><thead><tr>'
    cols.forEach((c: string) => { tableHtml += `<th>${c}</th>` })
    tableHtml += '</tr></thead><tbody>'
    rows.forEach((r: any) => {
      tableHtml += '<tr>'
      cols.forEach((c: string) => { tableHtml += `<td>${r[c] ?? ''}</td>` })
      tableHtml += '</tr>'
    })
    tableHtml += '</tbody></table>'
    const total = inner.row_count ?? rows.length
    if (total > 10) tableHtml += `<p style="color:#888;font-size:11px;">显示前 10 / 共 ${total} 行</p>`
    return { type: 'chatbi_table' as any, items: [{ title: `${total} 行`, url: '', snippet: tableHtml }] }
  }
  if (toolName === 'plot') {
    if (inner.error) return { type: 'error', message: inner.error }
    const opt = inner.echarts_option
    if (opt) {
      return { type: 'chatbi_chart' as any, items: [{ title: inner.chart_type || 'chart', url: '', snippet: JSON.stringify(opt) }] }
    }
    return { type: 'empty' }
  }

  const arr = Array.isArray(inner.results)
    ? inner.results
    : Array.isArray(inner.passages) ? inner.passages : null
  if (!arr) return null
  if (arr.length === 0) return { type: 'empty' }
  const items = arr
    .filter((r: any) => r && (r.title || r.url || r.snippet || r.content || r.text))
    .map((r: any) => {
      // RAG 结果：source 取文件名而非完整路径
      const rawTitle = r.title || r.name || r.source || '无标题'
      const title = (!r.url && rawTitle.includes('/')) ? rawTitle.split('/').pop() : rawTitle
      return {
        title,
        url: r.url || '',
        snippet: r.snippet || r.content || r.text || '',
      }
    })
  if (items.length === 0) return { type: 'empty' }
  return { type: 'search_ok', items }
}

function getToolRawText(block: LeftBlock): string {
  return block.metadata?.resultFull || block.metadata?.resultPreview || ''
}

function formattedToolJson(block: LeftBlock): string | null {
  const raw = block.metadata?.resultFull || block.metadata?.resultPreview || ''
  if (!raw) return null
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return null
  }
}

function extractDomain(url: string): string {
  try {
    const u = new URL(url)
    return u.hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

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

// ── 展开/收起、查看原文 ──
const expandedBlocks = ref<Record<string, boolean>>({})
const showRaw = ref<Record<string, boolean>>({})

function toggleExpand(blockId: string) {
  expandedBlocks.value[blockId] = !expandedBlocks.value[blockId]
}

function toggleRaw(blockId: string) {
  showRaw.value[blockId] = !showRaw.value[blockId]
}

// ── 决策标签 ──
const decisionLabels: Record<string, string> = {
  sufficient: '✅ 信息充足',
  need_more: '🔍 需要补搜',
  terminate: '⚠️ 强制终止',
}

function toolLabel(tool: string): string {
  const map: Record<string, string> = {
    search: '网络搜索', rag_retrieve: 'RAG 检索',
    gen_sql: '生成SQL', exec_sql: '执行SQL', plot: '图表生成',
  }
  return map[tool] || tool
}

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
  if (block.status !== 'done') return null
  if (!block.content) return null

  let src = block.content.trim()
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
    return null
  }
}

function getDecision(block: LeftBlock): string {
  return parsedBlockContent(block)?.decision || ''
}

/** 该 plan 在本轮 blocks 中是第几轮 Plan */
function planRound(block: LeftBlock): number {
  const plans = (props.blocks || []).filter(b => b.type === 'plan')
  return plans.findIndex(b => b.id === block.id) + 1
}

function getDecisionLabel(block: LeftBlock): string {
  const d = getDecision(block)
  if (d === 'need_more') {
    return planRound(block) >= 3 ? '🔍 需要补搜' : '❓ 信息不足'
  }
  return decisionLabels[d] || d
}

// ── chatBI 内联图表初始化 ──
const chartInstances = new Map<Element, echarts.ECharts>()
const pendingCharts = new Map<Element, string>()  // el -> optionJson，等待容器有尺寸

function initInlineChart(el: HTMLElement | null, optionJson: string | undefined) {
  if (!el || !optionJson) return
  // 已有实例且容器有尺寸 → resize 即可
  if (chartInstances.has(el)) {
    if (el.clientWidth > 0 && el.clientHeight > 0) {
      chartInstances.get(el)!.resize()
    }
    return
  }
  // 容器尺寸为 0 → 存起来，等可见时再 init
  if (el.clientWidth === 0 || el.clientHeight === 0) {
    pendingCharts.set(el, optionJson)
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
          obs.disconnect()
          pendingCharts.delete(el)
          doInitChart(el, optionJson)
        }
      }
    })
    obs.observe(el)
    return
  }
  doInitChart(el, optionJson)
}

function doInitChart(el: HTMLElement, optionJson: string) {
  if (chartInstances.has(el)) return
  try {
    const opt = JSON.parse(optionJson)
    opt.backgroundColor = 'transparent'
    const chart = echarts.init(el)
    chart.setOption(opt)
    chartInstances.set(el, chart)
    // 持续观察容器尺寸：移动端 tab 切换（display:none → 显示）时宽度变化，自动 resize
    const ro = new ResizeObserver(() => {
      if (el.clientWidth > 0 && el.clientHeight > 0) {
        chart.resize()
      }
    })
    ro.observe(el)
  } catch { /* ignore */ }
}

/** 强制刷新所有图表（移动端 tab 切换 / 容器恢复可见时调用） */
function resizeAllCharts() {
  // 先处理等待中的图表（容器刚有尺寸）
  for (const [el, opt] of pendingCharts) {
    if (el.clientWidth > 0 && el.clientHeight > 0) {
      pendingCharts.delete(el)
      doInitChart(el, opt)
    }
  }
  for (const chart of chartInstances.values()) {
    chart.resize()
  }
}

// 监听 tab 切换广播：切回聊天 tab 时强制全量 resize，确保 echarts 撑满容器
onMounted(() => {
  window.addEventListener('mindglass:charts-resize', resizeAllCharts)
})
onUnmounted(() => {
  window.removeEventListener('mindglass:charts-resize', resizeAllCharts)
})
</script>

<style scoped>
.thought-block {
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
}

.thought-plan { border-left: 3px solid #a78bfa; }
.thought-toolcall { border-left: 3px solid #f59e0b; }
.thought-observe { border-left: 3px solid #10b981; }
.thought-answer { border-left: 3px solid #3b82f6; }

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
  0%, 100% { opacity: 1; box-shadow: 0 0 4px var(--accent); }
  50% { opacity: 0.4; box-shadow: 0 0 12px var(--accent); }
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

.thought-content.is-loading {
  position: relative;
  animation: loadingPulse 2s ease-in-out infinite;
}

@keyframes loadingPulse {
  0%, 100% { border-bottom: 1px solid transparent; }
  50% { border-bottom: 1px solid rgba(167, 139, 250, 0.3); }
}

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
.thought-content :deep(pre code) { background: none; padding: 0; }
.thought-content :deep(ul),
.thought-content :deep(ol) { margin: 0.3em 0; padding-left: 1.5em; }
.thought-content :deep(li) { margin: 0.15em 0; }

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
  scrollbar-width: thin;
  scrollbar-color: rgba(167, 139, 250, 0.35) rgba(255, 255, 255, 0.04);
}

.thought-content.is-collapsed .tool-result { max-height: 200px; }
.thought-content:not(.is-collapsed) .tool-result { max-height: none; }

/* 工具结果 / JSON 原文 / 搜索结果 webkit 滚动条主题化 */
.tool-result::-webkit-scrollbar,
.json-body::-webkit-scrollbar,
.result-item::-webkit-scrollbar {
  width: 6px;
}
.tool-result::-webkit-scrollbar-track,
.json-body::-webkit-scrollbar-track,
.result-item::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 3px;
}
.tool-result::-webkit-scrollbar-thumb,
.json-body::-webkit-scrollbar-thumb,
.result-item::-webkit-scrollbar-thumb {
  background: rgba(167, 139, 250, 0.35);
  border-radius: 3px;
}
.tool-result::-webkit-scrollbar-thumb:hover,
.json-body::-webkit-scrollbar-thumb:hover,
.result-item::-webkit-scrollbar-thumb:hover {
  background: rgba(167, 139, 250, 0.6);
}

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

.result-item:hover { background: rgba(255, 255, 255, 0.05); }
.result-item.item-hidden { display: none; }

.result-title {
  display: inline-block;
  color: #60a5fa;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  margin-right: 8px;
}

.result-title:hover { text-decoration: underline; color: #93bbfc; }

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

.tool-error-msg {
  font-size: 13px;
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.3);
  border-radius: 6px;
  padding: 8px 12px;
  line-height: 1.5;
}

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
  scrollbar-width: thin;
  scrollbar-color: rgba(167, 139, 250, 0.35) rgba(255, 255, 255, 0.04);
}

.placeholder {
  color: var(--text-dim);
  font-style: italic;
  font-size: 12px;
}

.tool-parallel-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 8px;
}

@media (max-width: 768px) {
  .tool-parallel-grid { grid-template-columns: 1fr; }
}

.parallel-card { margin: 0; }
.parallel-card .thought-content { font-size: 12px; }

/* P1 人读视图 */
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

.readable-steps {
  margin: 4px 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-h);
}

.readable-steps li { margin-bottom: 4px; }

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

.step-desc { color: var(--text); }

.step-query {
  color: var(--text-dim);
  font-size: 12px;
  font-family: 'Fira Code', Consolas, monospace;
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

.readable-list {
  margin: 4px 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-h);
  scrollbar-width: thin;
  scrollbar-color: rgba(167, 139, 250, 0.35) rgba(255, 255, 255, 0.04);
}

.readable-list li { margin-bottom: 3px; }

.conflict-list { color: var(--text-h); }
.conflict-list strong { color: #fbbf24; }
.confidence { color: var(--text-dim); font-size: 12px; }

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

/* 分割线（打断/重试分支边界） */
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
.thought-block.phase-cut { opacity: 0.55; }
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

/* chatBI 工具结果样式 */
.sql-preview {
  background: #1a1a2e;
  color: #cdd6f4;
  padding: 8px 12px;
  border-radius: 6px;
  font-family: 'Fira Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
  max-height: 120px;
  overflow-y: auto;
}
.sql-preview::-webkit-scrollbar { width: 5px; height: 5px; }
.sql-preview::-webkit-scrollbar-track { background: rgba(255,255,255,0.03); border-radius: 3px; }
.sql-preview::-webkit-scrollbar-thumb { background: rgba(167,139,250,0.3); border-radius: 3px; }
.sql-preview::-webkit-scrollbar-thumb:hover { background: rgba(167,139,250,0.5); }

.chatbi-table-wrap :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.chatbi-table-wrap :deep(th),
.chatbi-table-wrap :deep(td) {
  border: 1px solid rgba(255,255,255,0.1);
  padding: 4px 8px;
  text-align: left;
  color: #fff;
}
.chatbi-table-wrap :deep(th) {
  background: rgba(167,139,250,0.15);
  font-weight: 600;
}
.chatbi-table-wrap :deep(tr:nth-child(even)) {
  background: rgba(255,255,255,0.02);
}

.inline-chart-container {
  width: 100%;
  height: 260px;
  border-radius: 6px;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.08);
}

@media (max-width: 767px) {
  .thought-title { font-size: 14px; }
  .thought-content { font-size: 14px; padding: 10px; }
  .readable-text, .readable-steps { font-size: 14px; }
  .readable-label { font-size: 13px; }
  .result-title { font-size: 14px; }
  .result-snippet { font-size: 13px; }
}
</style>
