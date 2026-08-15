<template>
  <div class="reasoning-graph">
    <VueFlow
      v-if="nodes.length > 0"
      ref="vueFlowRef"
      :nodes="nodes"
      :edges="edges"
      :default-viewport="{ x: 0, y: 0, zoom: 1 }"
      fit-view-on-init
      :min-zoom="0.5"
      :max-zoom="2"
      class="flow-container"
      @node-click="onNodeClick"
    />

    <div v-else class="empty-state">
      <div class="empty-icon"><MirrorIcon :size="54" /></div>
      <p class="empty-title">投一个问题，看思绪成形</p>
      <p class="empty-sub">推理过程将如星河般在你眼前生长</p>
    </div>

    <!-- 编辑侧边面板 -->
    <div v-if="editingNode" class="editor-panel" :class="{ 'panel-open': editingNode }">
      <div class="panel-header">
        <h3>✏️ 编辑节点</h3>
        <button class="close-btn" @click="closeEditor">✕</button>
      </div>

      <div class="panel-body">
        <div class="node-info">
          <span class="badge" :class="editingNode.type.toLowerCase()">{{ editingNode.type }}</span>
          <span class="step-label">Step {{ editingNode.step_index }}</span>
          <span v-if="editingNode.duration_ms" class="duration-badge">⏱ {{ formatDuration(editingNode.duration_ms) }}</span>
        </div>

        <!-- ToolCall 编辑 -->
        <template v-if="editingNode.type === 'ToolCall'">
          <div v-if="isDeprecatedNode" class="deprecated-hint-panel">
            ⚠️ 此工具调用已被废弃（被重试截断），仅保留供对比参考。
          </div>

          <!-- 只有 search/rag_retrieve 展示工具切换 + 查询输入 -->
          <template v-if="isSearchableTool">
            <label>工具选择</label>
            <select v-model="editForm.tool" class="select-field">
              <option value="search">🔍 搜索 (search)</option>
              <option value="rag_retrieve">📖 RAG 检索 (rag_retrieve)</option>
            </select>

            <label>查询内容</label>
            <input
              v-model="editForm.queryInput"
              class="input-field"
              placeholder="输入你想查询的内容..."
            />
          </template>

          <!-- gen_sql: 可编辑 SQL -->
          <template v-else-if="currentToolName === 'gen_sql'">
            <label>🛠️ 生成 SQL</label>
            <textarea
              v-model="editForm.sqlInput"
              class="input-field sql-textarea"
              rows="4"
              placeholder="SELECT ..."
            ></textarea>
          </template>

          <!-- exec_sql: 只读展示 SQL + 结果 -->
          <template v-else-if="currentToolName === 'exec_sql'">
            <label>⚙️ 执行 SQL（只读）</label>
            <pre class="sql-readonly">{{ editingNode.data?.params?.sql || '(无)' }}</pre>
            <div v-if="execSqlPreview" class="output-preview">
              <label>📊 查询结果（前 {{ execSqlPreview.row_count }} 行）</label>
              <div class="answer-content" v-html="execSqlPreviewHtml"></div>
            </div>
          </template>

          <!-- plot: 展示图表预览 -->
          <template v-else-if="currentToolName === 'plot'">
            <label>📈 图表生成</label>
            <div ref="plotPreviewRef" class="plot-preview-container"></div>
          </template>

          <!-- 其他未知工具：兜底展示 -->
          <template v-else>
            <label>工具: {{ currentToolName }}</label>
            <div v-if="toolCallResult" class="output-preview">
              <label>📤 输出结果</label>
              <div class="answer-content" v-html="md.render(toolCallResult)"></div>
            </div>
            <p v-else class="readonly-hint">暂无输出结果</p>
          </template>

          <!-- 通用输出结果（search/rag_retrieve 用） -->
          <div v-if="isSearchableTool && toolCallResult" class="output-preview">
            <label>📤 输出结果</label>
            <div class="answer-content" v-html="md.render(toolCallResult)"></div>
          </div>
          <p v-else-if="isSearchableTool && !toolCallResult" class="readonly-hint">暂无输出结果</p>
        </template>

        <!-- Plan 只读展示，不提供干预：要改规划不如重新输一个新 query -->
        <template v-else-if="editingNode.type === 'Plan'">
          <!-- 废弃提示：与 ToolCall/Observe 统一的黄色 warning 风格 -->
          <div v-if="isDeprecatedNode" class="deprecated-hint-panel">
            ⚠️ 此决策来自被废弃的推理分支，已被新版本替代，仅供参考对比。
          </div>
          <!-- 决策节点（Plan 2+）：展示决策 + 理由 -->
          <template v-if="isDecisionNode">
            <div class="decision-banner" :class="isDeprecatedNode ? 'decision-deprecated' : `decision-${planDecision}`">
              {{ planDecisionLabel }}
            </div>
            <label>决策理由</label>
            <div class="output-content">{{ planReasoning }}</div>

            <template v-if="planDecision === 'need_more'">
              <label>缺失方面</label>
              <ul class="info-list">
                <li v-for="(a, i) in planMissingAspects" :key="i">{{ a }}</li>
              </ul>
              <label>补搜计划</label>
              <ul class="info-list">
                <li v-for="(q, i) in planSuggestedQueries" :key="i">{{ q }}</li>
              </ul>
            </template>

            <template v-else-if="planDecision === 'terminate'">
              <label>终止说明</label>
              <div class="output-content terminate-note">{{ planTerminateNote }}</div>
            </template>
          </template>

          <!-- 初始规划（Plan 1）：展示思路 + 整洁步骤列表 -->
          <template v-else>
            <label>规划思路</label>
            <div class="output-content">{{ planReasoning }}</div>
            <label>步骤列表</label>
            <ol class="step-list">
              <li v-for="(s, i) in planSteps" :key="i">
                <span class="step-tool">{{ toolLabel(s.tool) }}</span>
                <span class="step-query">{{ s.params?.query || s.description || '' }}</span>
              </li>
            </ol>
            <p v-if="!planSteps.length" class="readonly-hint">暂无步骤</p>
          </template>
        </template>

        <!-- Observe 只展示 -->
        <template v-else-if="editingNode.type === 'Observe'">
          <div v-if="isDeprecatedNode" class="deprecated-hint-panel">
            ⚠️ 此评估结果已被新版本替代（来自废弃的搜索决策），仅供参考对比。
          </div>
          <div v-if="observeResult" class="output-preview observe-only">
            <label>👁️ 评估结果</label>
            <div class="answer-content" v-html="md.render(observeResult)"></div>
          </div>
          <p v-else class="readonly-hint">暂无评估结果</p>
        </template>

      </div>

      <div v-if="editingNode && editingNode.type === 'ToolCall' && !editingNode.data?.pending" class="panel-footer">
        <!-- 运行中：按钮为“截断”（已打断则置为执行中，不可重复截断） -->
        <template v-if="isRunning">
          <button class="retry-btn cut-btn" :disabled="!!cutNodeId" @click="handleInterrupt">
            {{ cutNodeId ? '⏸ 执行中...' : '✂️ 截断' }}
          </button>
          <p v-if="cutNodeId" class="readonly-hint">已打断，正在收尾…</p>
        </template>
        <!-- 打断后：只有截断点节点能点重试；其他节点只显示提示 -->
        <template v-else-if="cutNodeId">
          <button v-if="cutNodeId === editingNode.id" class="retry-btn" @click="handleRetry">
            🔄 重试
          </button>
          <p v-if="cutNodeId === editingNode.id" class="readonly-hint">✂️ 这是截断点，可修改参数后重试</p>
          <p v-else class="readonly-hint">✂️ 在哪里打断，就在哪里重试——请回到截断点节点</p>
        </template>
        <!-- 正常完成：保留原有截断并重试能力（显示为“重试”） -->
        <button v-else class="retry-btn" @click="handleRetry">🔄 重试</button>
      </div>
    </div>

    <!-- 断线重连浮层按钮：自动重连时显示进度，失败后变为可点击 -->
    <div v-if="(disconnected || autoRetrying) && nodes.length > 0" class="reconnect-overlay">
      <button
        class="reconnect-btn"
        :class="{ 'retrying': autoRetrying }"
        :disabled="autoRetrying"
        @click="!autoRetrying && emit('reconnect')"
      >
        {{ autoRetrying ? `🔄 正在尝试重连 (${autoRetryCount ?? 0}/3)...` : '📡 重新连接' }}
      </button>
      <span class="reconnect-hint">
        {{ autoRetrying ? '后端恢复后将自动继续推理' : '推理已中断 · 点击恢复最新状态' }}
      </span>
    </div>

    <!-- 废弃回答弹窗：被截断重试前的旧版回答，仅供对比参考 -->
    <div v-if="deprecatedAnswer" class="deprecated-overlay" @click.self="deprecatedAnswer = null">
      <div class="deprecated-modal">
        <div class="panel-header">
          <h3>🗑️ {{ deprecatedAnswer.label || '废弃回答' }}</h3>
          <button class="close-btn" @click="deprecatedAnswer = null">✕</button>
        </div>
        <div class="deprecated-body">
          <p class="deprecated-hint">⚠️ 这是被截断重试之前的旧版回答，已被废弃，仅供参考对比。</p>
          <div class="answer-content" v-html="md.render(deprecatedAnswer.data?.output || '（无内容）')"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { computed, ref, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import MirrorIcon from './MirrorIcon.vue'
import { useReasoningGraph } from '@/composables/useReasoningGraph'
import type { ReasoningGraph, AgentNode } from '@/types/agent'

const props = defineProps<{
  graph: ReasoningGraph | null
  isRunning: boolean
  cutNodeId: string | null
  disconnected?: boolean
  autoRetrying?: boolean
  autoRetryCount?: number
}>()

const emit = defineEmits<{
  (e: 'retry', stepIndex: number, originalNode: any, editedData: Record<string, any>): void
  (e: 'interrupt', node: AgentNode): void
  (e: 'focus-answer'): void
  (e: 'reconnect'): void
}>()
const graphRef = computed(() => props.graph)
const cutIdRef = computed(() => props.cutNodeId ?? null)
const { flowNodes: nodes, flowEdges: edges } = useReasoningGraph(graphRef, cutIdRef)

const { fitView } = useVueFlow()

// --- 编辑面板 ---
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

const editingNode = ref<AgentNode | null>(null)
/** 废弃回答弹窗（replaced/branch 状态的 Answer） */
const deprecatedAnswer = ref<AgentNode | null>(null)

/** 格式化耗时：毫秒 → "X.Ys" 或 "Xms" */
function formatDuration(ms: number): string {
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(1)}s`
  }
  return `${ms}ms`
}

// 输出预览 computed
const toolCallResult = computed(() => {
  if (!editingNode.value?.data?.result) return ''
  const r = editingNode.value.data.result

  // 兼容三种格式：search 的 results、rag_retrieve 的 passages、旧版 rag-es 的 sources
  const results = r.result?.results || r.result?.passages || r.result?.sources || r.results || r.passages || r.sources
  const answer = r.result?.answer || r.answer

  const parts: string[] = []

  // 先放 answer 总结（仅 search/旧版 rag-es 有）
  if (answer) {
    parts.push(`**摘要**：${answer}`)
  }

  // 分点列出检索结果
  if (Array.isArray(results) && results.length > 0) {
    const items = results.map((x: any, i: number) => {
      // RAG 结果：content + source + score
      if (x.content && !x.snippet && !x.url) {
        const source = x.source ? ` (${x.source.split('/').pop()})` : ''
        const score = x.score != null ? ` [相关度: ${x.score}]` : ''
        const content = x.content.length > 500 ? x.content.slice(0, 500) + '...' : x.content
        return `${i + 1}. **段落${i + 1}**${source}${score}\n${content}`
      }
      // Search 结果：title + url + snippet
      const title = x.title || x.url || '无标题'
      const snippet = x.snippet || x.content || ''
      const url = x.url ? ` ([链接](${x.url}))` : ''
      return `${i + 1}. **${title}**${url}\n${snippet}`
    }).join('\n\n')
    parts.push(items)
  }

  return parts.join('\n\n---\n\n')
})

// ── chatBI 工具弹窗辅助 ──
const currentToolName = computed(() => editingNode.value?.data?.tool || '')
const isSearchableTool = computed(() => ['search', 'rag_retrieve'].includes(currentToolName.value))

const execSqlPreview = computed(() => {
  if (currentToolName.value !== 'exec_sql') return null
  const r = editingNode.value?.data?.result?.result || editingNode.value?.data?.result
  if (!r || !r.columns) return null
  return { columns: r.columns, rows: (r.rows || []).slice(0, 20), row_count: r.row_count ?? r.rows?.length ?? 0 }
})

const execSqlPreviewHtml = computed(() => {
  const p = execSqlPreview.value
  if (!p || !p.rows.length) return '<em>无数据</em>'
  let html = '<table><thead><tr>'
  p.columns.forEach((c: string) => { html += `<th>${c}</th>` })
  html += '</tr></thead><tbody>'
  p.rows.forEach((row: any) => {
    html += '<tr>'
    p.columns.forEach((c: string) => { html += `<td>${row[c] ?? ''}</td>` })
    html += '</tr>'
  })
  html += '</tbody></table>'
  if (p.row_count > 20) html += `<p style="color:#888;font-size:12px;">显示前 20 / 共 ${p.row_count} 行</p>`
  return html
})

// plot 图表预览（节点打开时初始化）
import * as echarts from 'echarts'
const plotPreviewRef = ref<HTMLElement | null>(null)
let plotChartInstance: echarts.ECharts | null = null

watch(editingNode, (node) => {
  if (node?.data?.tool === 'plot') {
    nextTick(() => {
      if (plotPreviewRef.value) {
        const r = node.data?.result?.result || node.data?.result
        const opt = r?.echarts_option
        if (opt) {
          if (plotChartInstance) plotChartInstance.dispose()
          plotChartInstance = echarts.init(plotPreviewRef.value)
          opt.backgroundColor = 'transparent'
          plotChartInstance.setOption(opt)
        } else {
          plotPreviewRef.value.innerHTML = '<span style="color:#f87171">无图表数据</span>'
        }
      }
    })
  }
}, { immediate: true })

/** v2: 渲染结构化 Observe 评估输出 */
function buildStructuredObserve(obs: any): string {
  const parts: string[] = []
  if (obs.round) parts.push(`**第 ${obs.round} 轮评估**`)
  if (obs.summary) parts.push(obs.summary)
  const findings = obs.key_findings || []
  if (findings.length) {
    parts.push('**要点**')
    findings.forEach((f: string, i: number) => parts.push(`${i + 1}. ${f}`))
    parts.push('')
  }
  const conflicts = obs.conflicts || []
  if (conflicts.length) {
    parts.push('**矛盾处理**')
    conflicts.forEach((c: any) => {
      parts.push(`- **${c.topic || '矛盾'}**（置信度: ${c.confidence || '?'}）`)
      if (c.resolution) parts.push(`  处理：${c.resolution}`)
    })
    parts.push('')
  }
  if (obs.duplicates_removed) parts.push(`*去重 ${obs.duplicates_removed} 条重复结果*`)
  if (obs.new_info_vs_previous && obs.round > 1) parts.push(`*新增信息：${obs.new_info_vs_previous}*`)
  return parts.join('\n')
}

const observeResult = computed(() => {
  const data = editingNode.value?.data
  if (!data) return ''
  // v2: 结构化 observe_output 优先
  if (data.observe_output) {
    return buildStructuredObserve(data.observe_output)
  }
  if (!data.result_summary) return ''
  const summary = data.result_summary

  // 先试标准 JSON（新数据）
  try {
    const parsed = JSON.parse(summary)
    return buildObserveOutput(parsed)
  } catch { /* continue */ }

  // 兼容旧数据：Python str(dict) 单引号格式
  try {
    // 转义内容中的双引号后再替换
    const safeStr = summary
      .replace(/\\"/g, '__DQ__')  // 保护已转义的双引号
      .replace(/"/g, '__DQ__')    // 保护原始双引号
      .replace(/'/g, '"')
      .replace(/__DQ__/g, '"')
      .replace(/\bTrue\b/g, 'true')
      .replace(/\bFalse\b/g, 'false')
      .replace(/\bNone\b/g, 'null')
    const parsed = JSON.parse(safeStr)
    return buildObserveOutput(parsed)
  } catch { /* continue */ }

  return ''
})

function buildObserveOutput(parsed: any): string {
  // 合并 Observe 格式：列表 [{result: {results: [...], answer: "..."}}, ...]
  if (Array.isArray(parsed)) {
    const parts: string[] = []
    parsed.forEach((item: any, idx: number) => {
      const itemResult = item.result || item
      const answer = itemResult.answer || ''
      const results = itemResult.results || []
      if (answer) {
        parts.push(`**摘要**：${answer}`)
      }
      if (Array.isArray(results) && results.length > 0) {
        const items = results.map((x: any, i: number) => {
          const title = x.title || x.url || '无标题'
          const snippet = x.snippet || x.content || ''
          const url = x.url ? ` ([链接](${x.url}))` : ''
          return `${i + 1}. **${title}**${url}\n${snippet}`
        }).join('\n\n')
        parts.push(items)
      }
    })
    return parts.join('\n\n---\n\n')
  }

  // 单个 Observe 格式：{result: {results: [...], answer: "..."}}
  const results = parsed.result?.results
  const answer = parsed.result?.answer || parsed.answer
  const parts: string[] = []

  if (answer) {
    parts.push(`**摘要**：${answer}`)
  }

  if (Array.isArray(results) && results.length > 0) {
    const items = results.map((x: any, i: number) => {
      const title = x.title || x.url || '无标题'
      const snippet = x.snippet || x.content || ''
      const url = x.url ? ` ([链接](${x.url}))` : ''
      return `${i + 1}. **${title}**${url}\n${snippet}`
    }).join('\n\n')
    parts.push(items)
  }

  return parts.join('\n\n---\n\n')
}

// ── Plan 面板只读展示 ──
const DECISION_LABELS: Record<string, string> = {
  sufficient: '✅ 决策：信息充足',
  need_more: '🔍 决策：信息不足',
  terminate: '⚠️ 决策：强制终止',
}

/** 决策横幅文案：第 2 轮（首轮决策）说“信息不足”，第 3 轮起才说“需要补搜”，与节点标签一致 */
const planDecisionLabel = computed(() => {
  const pc = editingNode.value?.data?.plan_count ?? 1
  if (planDecision.value === 'need_more') {
    return pc >= 3 ? '🔍 决策：需要补搜' : '🔍 决策：信息不足'
  }
  return DECISION_LABELS[planDecision.value] || planDecision.value
})

/** 工具中文名（与后端 TOOL_LABELS 保持一致） */
function toolLabel(tool: string): string {
  const map: Record<string, string> = {
    search: '网络搜索', rag_retrieve: 'RAG 检索',
    gen_sql: '生成SQL', exec_sql: '执行SQL', plot: '图表生成',
  }
  return map[tool] || tool
}

/** 是否为废弃节点（branch / replaced 状态） */
const isDeprecatedNode = computed(() => {
  const s = editingNode.value?.status
  return s === 'branch' || s === 'replaced' || s === 'discarded'
})

/** 是否为决策节点（Plan 2+）；Plan 1 是初始规划 */
const isDecisionNode = computed(() => (editingNode.value?.data?.plan_count ?? 1) >= 2)
const planDecision = computed(() => editingNode.value?.data?.decision || '')
const planReasoning = computed(() => editingNode.value?.data?.reasoning || editingNode.value?.data?.output || '')
const planMissingAspects = computed(() => editingNode.value?.data?.if_need_more?.missing_aspects || [])
const planSuggestedQueries = computed(() => editingNode.value?.data?.if_need_more?.suggested_queries || [])
const planTerminateNote = computed(() =>
  editingNode.value?.data?.if_terminate?.partial_answer_note ||
  editingNode.value?.data?.if_terminate?.reason || ''
)
const planSteps = computed(() => editingNode.value?.data?.steps || [])

const editForm = ref<Record<string, any>>({})

function onNodeClick({ node }: { node: { id: string } }) {
  const target = props.graph?.nodes.find(n => n.id === node.id)
  if (!target) return

  // 前端预测的虚拟 pending 节点：不可点开编辑（自然没有截断/重试按钮）
  if (target.status === 'pending' || target.data?.pending) return

  // Answer 节点：废弃回答用弹窗展示旧内容；实际最终回答聚焦聊天区
  if (target.type === 'Answer') {
    if (target.status === 'replaced' || target.status === 'branch') {
      deprecatedAnswer.value = target
    } else {
      emit('focus-answer')
    }
    return
  }

  editingNode.value = target

  // 初始化表单
  if (target.type === 'ToolCall') {
    const toolName = target.data.tool || ''
    editForm.value = {
      tool: toolName,
      queryInput: target.data.params?.query || '',
      sqlInput: target.data.params?.sql || target.data.result?.result?.sql || target.data.result?.sql || '',
    }
  } else if (target.type === 'Plan') {
    editForm.value = {
      output: target.data.output || '',
      stepsJson: JSON.stringify(target.data.steps || [], null, 2),
    }
  }
  // Observe / Answer 不需要编辑表单
}

function closeEditor() {
  editingNode.value = null
  editForm.value = {}
}

function handleInterrupt() {
  if (!editingNode.value) return
  // 拷贝当前节点完整信息，交给 composable 记录为截断点
  emit('interrupt', JSON.parse(JSON.stringify(editingNode.value)))
}

// 图更新后同步编辑面板引用的节点对象（打断后节点状态/标签会变，面板要跟着新）
watch(
  () => props.graph?.nodes,
  () => {
    if (!editingNode.value) return
    const fresh = props.graph?.nodes.find(n => n.id === editingNode.value!.id)
    if (fresh) editingNode.value = fresh
  }
)

async function handleRetry() {
  if (!editingNode.value) return

  // 拷贝原节点完整信息（哥哥的方案：新旧都加标记）
  const originalNode = JSON.parse(JSON.stringify(editingNode.value))

  let editedData: Record<string, any> = {}

  if (editingNode.value.type === 'ToolCall') {
    editedData = {
      tool: editForm.value.tool,
      params: { query: editForm.value.queryInput || '' },
    }
  } else if (editingNode.value.type === 'Plan') {
    try {
      editedData = {
        output: editForm.value.output,
        steps: JSON.parse(editForm.value.stepsJson),
      }
    } catch {
      alert('步骤 JSON 格式错误')
      return
    }
  }

  // 传递：原节点完整副本 + 编辑后的新数据
  emit('retry', editingNode.value.step_index, originalNode, editedData)
  closeEditor()
}

// 监听节点数量变化，当有 Answer 节点时自动适配视图
watch(
  () => nodes.value.length,
  (newLen, oldLen) => {
    if (newLen > oldLen && newLen > 0) {
      const lastNode = nodes.value[nodes.value.length - 1]
      if (lastNode?.data?.type === 'Answer') {
        setTimeout(() => {
          fitView({ padding: 0.2, duration: 300 })
        }, 100)
      }
    }
  }
)
</script>

<style scoped>
.reasoning-graph {
  height: 100%;
  width: 100%;
  position: relative;
}

.flow-container {
  width: 100%;
  height: 100%;
  background: transparent; /* 水镜：全透，深空星野即水面 */
}

.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: var(--text-dim);
}

.empty-icon {
  font-size: 52px;
  margin-bottom: 16px;
  color: var(--accent);
  filter: drop-shadow(0 0 18px rgba(167, 139, 250, 0.45));
  animation: emptyFloat 4s ease-in-out infinite;
}

@media (max-width: 768px) {
  .empty-icon {
    font-size: 40px;
    margin-bottom: 12px;
  }
}

.empty-title {
  font-size: 19px;
  color: var(--text);
  letter-spacing: 2px;
  margin-bottom: 8px;
  text-shadow: 0 0 24px rgba(167, 139, 250, 0.3);
}

@media (max-width: 768px) {
  .empty-title {
    font-size: 16px;
    letter-spacing: 1px;
  }
}

.empty-sub {
  font-size: 13px;
  color: var(--text-dim);
  letter-spacing: 1px;
}

@media (max-width: 768px) {
  .empty-sub {
    font-size: 12px;
  }
}

@keyframes emptyFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

/* --- 编辑侧边面板 —— 深空主题 --- */
.editor-panel {
  position: absolute;
  top: 0;
  right: -420px;
  width: 400px;
  height: 100%;
  background: rgba(10, 14, 31, 0.92);
  backdrop-filter: blur(16px);
  border-left: 1px solid rgba(96, 165, 250, 0.4);
  box-shadow: -4px 0 24px rgba(96, 165, 250, 0.15), -2px 0 0 rgba(96, 165, 250, 0.1);
  transition: right 0.3s ease;
  display: flex;
  flex-direction: column;
  z-index: 100;
}

@media (max-width: 768px) {
  .editor-panel {
    width: 100%;
    right: auto;
    left: 0;
    top: auto;
    bottom: -100%;
    height: 70%;
    border-left: none;
    border-top: 1px solid rgba(96, 165, 250, 0.4);
    box-shadow: 0 -4px 24px rgba(96, 165, 250, 0.15), 0 -2px 0 rgba(96, 165, 250, 0.1);
    transition: bottom 0.3s ease;
  }
  .panel-open {
    bottom: 0;
    right: auto;
  }
}

/* 侧边面板 + 废弃弹窗滚动条主题化（与左侧水镜统一） */
.panel-body,
.deprecated-body {
  scrollbar-width: thin;
  scrollbar-color: rgba(167, 139, 250, 0.35) rgba(255, 255, 255, 0.04);
}
.panel-body::-webkit-scrollbar,
.deprecated-body::-webkit-scrollbar {
  width: 8px;
}
.panel-body::-webkit-scrollbar-track,
.deprecated-body::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.04);
  border-radius: 4px;
}
.panel-body::-webkit-scrollbar-thumb,
.deprecated-body::-webkit-scrollbar-thumb {
  background: rgba(167, 139, 250, 0.35);
  border-radius: 4px;
  transition: background 0.2s;
}
.panel-body::-webkit-scrollbar-thumb:hover,
.deprecated-body::-webkit-scrollbar-thumb:hover {
  background: rgba(167, 139, 250, 0.6);
}

.panel-open {
  right: 0;
}

/* --- 废弃回答弹窗 —— 深空主题 --- */
.deprecated-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.deprecated-modal {
  width: min(720px, 92%);
  max-height: 86%;
  background: rgba(10, 14, 31, 0.95);
  backdrop-filter: blur(16px);
  border-radius: 12px;
  border: 1px solid rgba(192, 192, 220, 0.3);
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(192, 192, 220, 0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-top: 3px solid rgba(192, 192, 220, 0.5);
}

@media (max-width: 768px) {
  .deprecated-modal {
    width: 96%;
    max-height: 80%;
  }
}

.deprecated-modal .panel-header {
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding: 14px 18px;
}

.deprecated-modal .panel-header h3 {
  font-size: 15px;
  color: #c0c0dc;
}

.deprecated-body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px;
  color: #e6e9f5;
}

.deprecated-hint {
  background: rgba(255, 251, 230, 0.1);
  border: 1px solid rgba(255, 229, 143, 0.4);
  border-radius: 8px;
  color: #fbbf24;
  font-size: 13px;
  padding: 8px 12px;
  margin-bottom: 14px;
}

.deprecated-body .answer-content {
  color: #e6e9f5;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: #e6e9f5;
}

.close-btn {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: #6b6b80;
  padding: 4px 8px;
  transition: color 0.2s;
}

.close-btn:hover {
  color: #e6e9f5;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  color: #e6e9f5;
}

.node-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.badge {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.badge.plan {
  background: rgba(96, 165, 250, 0.15);
  color: #60a5fa;
  border: 1px solid rgba(96, 165, 250, 0.3);
}

.badge.toolcall {
  background: rgba(251, 191, 36, 0.15);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.3);
}

.badge.observe {
  background: rgba(52, 211, 153, 0.15);
  color: #34d399;
  border: 1px solid rgba(52, 211, 153, 0.3);
}

.badge.answer {
  background: rgba(196, 181, 253, 0.15);
  color: #c4b5fd;
  border: 1px solid rgba(196, 181, 253, 0.3);
}

.step-label {
  font-size: 13px;
  color: #a7a7ba;
}

.duration-badge {
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.06);
  color: #a7a7ba;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  font-family: 'Menlo', 'Monaco', monospace;
}

/* 废弃提示横幅 */
.deprecated-hint-panel {
  background: rgba(255, 251, 230, 0.1);
  border: 1px solid rgba(255, 229, 143, 0.3);
  border-radius: 8px;
  color: #fbbf24;
  font-size: 13px;
  padding: 8px 12px;
  margin-bottom: 12px;
}

label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #c0c0dc;
  margin-bottom: 4px;
  margin-top: 12px;
}

.input-field,
.textarea-field {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  font-size: 13px;
  font-family: 'Menlo', 'Monaco', monospace;
  resize: vertical;
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.04);
  color: #e6e9f5;
}

.input-field:focus,
.textarea-field:focus {
  outline: none;
  border-color: #60a5fa;
  box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.2);
}

.select-field {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  font-size: 13px;
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.04);
  color: #e6e9f5;
  cursor: pointer;
}

.select-field:focus {
  outline: none;
  border-color: #60a5fa;
  box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.2);
}

.select-field option {
  background: #1a1e3a;
  color: #e6e9f5;
}

.readonly-hint {
  color: #6b6b80;
  font-style: italic;
  margin-top: 8px;
}

/* ── Plan 面板：决策展示（深空主题）── */
.decision-banner {
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 12px;
}
.decision-sufficient {
  background: rgba(52, 211, 153, 0.12);
  color: #34d399;
  border: 1px solid rgba(52, 211, 153, 0.4);
}
.decision-need_more {
  background: rgba(251, 191, 36, 0.12);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.4);
}
.decision-terminate {
  background: rgba(248, 113, 113, 0.12);
  color: #f87171;
  border: 1px solid rgba(248, 113, 113, 0.4);
}
.decision-deprecated {
  background: rgba(255, 255, 255, 0.04);
  color: #6b6b80;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.info-list {
  margin: 4px 0 8px;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.7;
  color: #c0c0dc;
}

.step-list {
  margin: 4px 0 8px;
  padding-left: 22px;
  font-size: 13px;
  line-height: 1.8;
}
.step-list li {
  margin-bottom: 6px;
}
.step-tool {
  display: inline-block;
  background: rgba(96, 165, 250, 0.12);
  color: #60a5fa;
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 12px;
  font-weight: 600;
  margin-right: 8px;
  border: 1px solid rgba(96, 165, 250, 0.25);
}
.step-query {
  color: #c0c0dc;
}

.terminate-note {
  border-left: 3px solid #fbbf24;
  background: rgba(255, 251, 230, 0.08);
}

/* 输出预览区域（深空主题） */
.output-preview {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.output-preview label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #c0c0dc;
  margin-bottom: 8px;
}

.output-content {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  text-align: left;
  max-height: 300px;
  overflow-y: auto;
  color: #c0c0dc;
}

.answer-content {
  text-align: left;
  font-size: 13px;
  line-height: 1.7;
  color: #e6e9f5;
}

.answer-content :deep(h1),
.answer-content :deep(h2),
.answer-content :deep(h3) {
  margin: 0.8em 0 0.4em;
  font-weight: 600;
  color: #e6e9f5;
}
.answer-content :deep(h1) { font-size: 1.1em; }
.answer-content :deep(h2) { font-size: 1.05em; }
.answer-content :deep(h3) { font-size: 1em; }

.answer-content :deep(p) { margin: 0.4em 0; color: #c0c0dc; }
.answer-content :deep(code) {
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  color: #cdd6f4;
  font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace;
}
.answer-content :deep(pre) {
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 0.5em 0;
}
.answer-content :deep(pre code) { background: none; padding: 0; color: inherit; }
.answer-content :deep(strong) { font-weight: 600; color: #e6e9f5; }

.panel-footer {
  padding: 12px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.retry-btn {
  width: 100%;
  padding: 10px;
  background: #60a5fa;
  color: #0a0e1f;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.retry-btn:hover {
  background: #93bbfc;
}

.retry-btn:disabled {
  background: rgba(255, 255, 255, 0.08);
  color: #6b6b80;
  cursor: not-allowed;
}

/* 截断按钮：琥珀色，与截断点节点呼应 */
.retry-btn.cut-btn {
  background: rgba(251, 191, 36, 0.85);
  color: #1a1400;
}

.retry-btn.cut-btn:hover {
  background: #fbbf24;
}

.retry-btn.cut-btn:disabled {
  background: rgba(255, 255, 255, 0.08);
  color: #6b6b80;
  cursor: not-allowed;
}

/* ── 断线重连浮层按钮 ── */
.reconnect-overlay {
  position: absolute;
  bottom: 48px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  z-index: 90;
  pointer-events: auto;
}

.reconnect-btn {
  padding: 12px 32px;
  background: rgba(96, 165, 250, 0.9);
  color: #0a0e1f;
  border: 2px solid rgba(96, 165, 250, 0.6);
  border-radius: 24px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  backdrop-filter: blur(12px);
  box-shadow: 0 0 20px rgba(96, 165, 250, 0.4), 0 4px 16px rgba(0, 0, 0, 0.3);
  transition: all 0.25s ease;
  animation: reconnectPulse 2s ease-in-out infinite;
}

.reconnect-btn:hover:not(:disabled) {
  background: rgba(147, 187, 252, 0.95);
  box-shadow: 0 0 30px rgba(96, 165, 250, 0.6), 0 4px 20px rgba(0, 0, 0, 0.4);
  transform: scale(1.05);
}

.reconnect-btn.retrying {
  background: rgba(96, 165, 250, 0.5);
  cursor: wait;
  animation: reconnectPulse 1.5s ease-in-out infinite;
}

.reconnect-hint {
  font-size: 12px;
  color: rgba(192, 192, 220, 0.8);
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.6);
  letter-spacing: 0.5px;
}

@keyframes reconnectPulse {
  0%, 100% { box-shadow: 0 0 20px rgba(96, 165, 250, 0.4), 0 4px 16px rgba(0, 0, 0, 0.3); }
  50% { box-shadow: 0 0 32px rgba(96, 165, 250, 0.7), 0 4px 20px rgba(0, 0, 0, 0.4); }
}

@media (max-width: 768px) {
  .reconnect-overlay {
    bottom: 72px; /* 手机端避开底部导航栏 */
  }
  .reconnect-btn {
    padding: 14px 28px;
    font-size: 16px;
  }
}

/* ═══ 手机端响应式增强 ═══ */
@media (max-width: 767px) {
  .editor-panel {
    height: 75%;
    border-radius: 16px 16px 0 0;
  }

  .panel-body {
    padding: 12px;
    font-size: 14px;
  }

  .panel-header {
    padding: 12px;
  }

  .panel-header h3 {
    font-size: 15px;
  }

  .node-info {
    flex-wrap: wrap;
    gap: 6px;
  }

  label {
    font-size: 14px;
  }

  .input-field,
  .textarea-field,
  .select-field {
    font-size: 16px; /* 防止 iOS 缩放 */
    padding: 10px 12px;
  }

  .output-content {
    font-size: 13px;
    padding: 10px;
  }

  .step-list {
    font-size: 14px;
  }

  .step-tool {
    font-size: 13px;
  }

  .decision-banner {
    font-size: 13px;
    padding: 6px 10px;
  }

  .retry-btn {
    padding: 12px;
    font-size: 15px;
  }

  .panel-footer {
    padding: 12px;
  }

  .deprecated-modal {
    width: 96%;
    max-height: 85%;
    border-radius: 16px;
  }

  .deprecated-body {
    padding: 14px 16px;
    font-size: 14px;
  }

  .answer-content {
    font-size: 14px;
  }
}

/* chatBI 工具弹窗样式 */
.sql-textarea {
  font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace;
  font-size: 13px;
  resize: vertical;
  min-height: 80px;
}

.sql-readonly {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  padding: 8px 12px;
  font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace;
  font-size: 13px;
  color: var(--text-h);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow-y: auto;
  margin: 4px 0;
}

.plot-preview-container {
  width: 100%;
  height: 280px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--panel-border);
  margin-top: 4px;
}
</style>

<style>
/* 截断点节点呼吸动画（vue-flow 节点 class，需全局样式生效） */
.cut-node-pulse {
  animation: cutPulse 1.6s ease-in-out infinite;
}

@keyframes cutPulse {
  0%, 100% { box-shadow: 0 0 10px rgba(251, 191, 36, 0.35); }
  50% { box-shadow: 0 0 26px rgba(251, 191, 36, 0.8); }
}
</style>
