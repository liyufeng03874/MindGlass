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
      <div class="empty-icon">🧠</div>
      <p>发送问题后，推理过程将在这里展示</p>
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

          <!-- 输出结果（只展示 answer） -->
          <div v-if="toolCallResult" class="output-preview">
            <label>📤 输出结果</label>
            <div class="answer-content" v-html="md.render(toolCallResult)"></div>
          </div>
          <p v-else class="readonly-hint">暂无输出结果</p>
        </template>

        <!-- Plan 只读展示，不提供干预：要改规划不如重新输一个新 query -->
        <template v-else-if="editingNode.type === 'Plan'">
          <!-- 决策节点（Plan 2+）：展示决策 + 理由 -->
          <template v-if="isDecisionNode">
            <div class="decision-banner" :class="`decision-${planDecision}`">
              {{ DECISION_LABELS[planDecision] || planDecision }}
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
          <div v-if="observeResult" class="output-preview observe-only">
            <label>👁️ 评估结果</label>
            <div class="answer-content" v-html="md.render(observeResult)"></div>
          </div>
          <p v-else class="readonly-hint">暂无评估结果</p>
        </template>

      </div>

      <div v-if="editingNode && !['Observe', 'Plan'].includes(editingNode.type)" class="panel-footer">
        <button class="retry-btn" @click="handleRetry" :disabled="isRunning">
          {{ isRunning ? '执行中...' : '🔄 截断并重试' }}
        </button>
      </div>
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
import { computed, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { useReasoningGraph } from '@/composables/useReasoningGraph'
import type { ReasoningGraph, AgentNode } from '@/types/agent'

const props = defineProps<{
  graph: ReasoningGraph | null
  isRunning: boolean
}>()

const emit = defineEmits<{
  (e: 'retry', stepIndex: number, editedData: Record<string, any>): void
  (e: 'focus-answer'): void
}>()

const vueFlowRef = ref(null)
const graphRef = computed(() => props.graph)
const { flowNodes: nodes, flowEdges: edges } = useReasoningGraph(graphRef)

const { fitView } = useVueFlow()

// --- 编辑面板 ---
const md = new MarkdownIt({ breaks: true, linkify: true })

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

  const results = r.result?.results || r.results
  const answer = r.result?.answer || r.answer

  const parts: string[] = []

  // 先放 answer 总结
  if (answer) {
    parts.push(`**摘要**：${answer}`)
  }

  // 再分点列出搜索结果
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
})

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
  need_more: '🔍 决策：需要补搜',
  terminate: '⚠️ 决策：强制终止',
}

/** 工具中文名（与后端 TOOL_LABELS 保持一致） */
function toolLabel(tool: string): string {
  const map: Record<string, string> = { search: '网络搜索', rag_retrieve: 'RAG 检索' }
  return map[tool] || tool
}

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
    editForm.value = {
      tool: target.data.tool || '',
      queryInput: target.data.params?.query || '',
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
  background: #fafafa;
}

.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #999;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

/* --- 编辑侧边面板 --- */
.editor-panel {
  position: absolute;
  top: 0;
  right: -420px;
  width: 400px;
  height: 100%;
  background: #fff;
  border-left: 1px solid #e0e0e0;
  box-shadow: -4px 0 16px rgba(0, 0, 0, 0.08);
  transition: right 0.3s ease;
  display: flex;
  flex-direction: column;
  z-index: 100;
}

.panel-open {
  right: 0;
}

/* --- 废弃回答弹窗 --- */
.deprecated-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.deprecated-modal {
  width: min(720px, 92%);
  max-height: 86%;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-top: 4px solid #bfbfbf;
}

.deprecated-modal .panel-header {
  background: #fafafa;
  border-bottom: 1px solid #eee;
  padding: 14px 18px;
}

.deprecated-modal .panel-header h3 {
  font-size: 15px;
  color: #8c8c8c;
}

.deprecated-body {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px;
}

.deprecated-hint {
  background: #fffbe6;
  border: 1px solid #ffe58f;
  border-radius: 8px;
  color: #ad8b00;
  font-size: 13px;
  padding: 8px 12px;
  margin-bottom: 14px;
}

.deprecated-body .answer-content {
  color: #595959;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #eee;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: #333;
}

.close-btn {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: #999;
  padding: 4px 8px;
}

.close-btn:hover {
  color: #333;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
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
  background: #e3f2fd;
  color: #1976d2;
}

.badge.toolcall {
  background: #fff3e0;
  color: #f57c00;
}

.badge.observe {
  background: #e8f5e9;
  color: #388e3c;
}

.badge.answer {
  background: #f3e5f5;
  color: #7b1fa2;
}

.step-label {
  font-size: 13px;
  color: #888;
}

.duration-badge {
  padding: 2px 8px;
  background: #f0f0f0;
  color: #666;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  font-family: 'Menlo', 'Monaco', monospace;
}

label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #555;
  margin-bottom: 4px;
  margin-top: 12px;
}

.input-field,
.textarea-field {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 13px;
  font-family: 'Menlo', 'Monaco', monospace;
  resize: vertical;
  box-sizing: border-box;
}

.input-field:focus,
.textarea-field:focus {
  outline: none;
  border-color: #1976d2;
  box-shadow: 0 0 0 2px rgba(25, 118, 210, 0.15);
}

.readonly-hint {
  color: #999;
  font-style: italic;
  margin-top: 8px;
}

/* ── Plan 面板：决策展示 ── */
.decision-banner {
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 12px;
}
.decision-sufficient {
  background: #f6ffed;
  color: #389e0d;
  border: 1px solid #b7eb8f;
}
.decision-need_more {
  background: #fff7e6;
  color: #d46b08;
  border: 1px solid #ffd591;
}
.decision-terminate {
  background: #fff2f0;
  color: #cf1322;
  border: 1px solid #ffccc7;
}

.info-list {
  margin: 4px 0 8px;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.7;
  color: #444;
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
  background: #e8f4fd;
  color: #1677ff;
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 12px;
  font-weight: 600;
  margin-right: 8px;
}
.step-query {
  color: #444;
}

.terminate-note {
  border-left: 3px solid #fa8c16;
  background: #fffbe6;
}

/* 输出预览区域 */
.output-preview {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #eee;
}

.output-preview label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #555;
  margin-bottom: 8px;
}

.output-content {
  background: #f8f9fa;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  text-align: left;
  max-height: 300px;
  overflow-y: auto;
  color: #333;
}

.answer-content {
  text-align: left;
  font-size: 13px;
  line-height: 1.7;
  color: #333;
}

.answer-content :deep(h1),
.answer-content :deep(h2),
.answer-content :deep(h3) {
  margin: 0.8em 0 0.4em;
  font-weight: 600;
}
.answer-content :deep(h1) { font-size: 1.1em; }
.answer-content :deep(h2) { font-size: 1.05em; }
.answer-content :deep(h3) { font-size: 1em; }

.answer-content :deep(p) { margin: 0.4em 0; }
.answer-content :deep(code) {
  background: rgba(0,0,0,0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
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
.answer-content :deep(strong) { font-weight: 600; }

.panel-footer {
  padding: 12px 16px;
  border-top: 1px solid #eee;
}

.retry-btn {
  width: 100%;
  padding: 10px;
  background: #1976d2;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.retry-btn:hover {
  background: #1565c0;
}

.retry-btn:disabled {
  background: #ccc;
  cursor: not-allowed;
}
</style>
