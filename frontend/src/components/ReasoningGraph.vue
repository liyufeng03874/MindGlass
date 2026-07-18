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

        <!-- Plan 编辑 -->
        <template v-else-if="editingNode.type === 'Plan'">
          <label>规划思路</label>
          <textarea v-model="editForm.output" class="textarea-field" rows="4" />

          <label>步骤列表（JSON）</label>
          <textarea
            v-model="editForm.stepsJson"
            class="textarea-field"
            rows="8"
            placeholder='[{"tool": "...", "params": {...}}]'
          />
        </template>

        <!-- Observe 只展示 -->
        <template v-else-if="editingNode.type === 'Observe'">
          <div v-if="observeResult" class="output-preview observe-only">
            <label>👁️ 观察结果</label>
            <div class="answer-content" v-html="md.render(observeResult)"></div>
          </div>
          <p v-else class="readonly-hint">暂无观察结果</p>
        </template>

      </div>

      <div v-if="editingNode && editingNode.type !== 'Observe'" class="panel-footer">
        <button class="retry-btn" @click="handleRetry" :disabled="isRunning">
          {{ isRunning ? '执行中...' : '🔄 截断并重试' }}
        </button>
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

const observeResult = computed(() => {
  if (!editingNode.value?.data?.result_summary) return ''
  const summary = editingNode.value.data.result_summary

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
const editForm = ref<Record<string, any>>({})

function onNodeClick({ node }: { node: { id: string } }) {
  const target = props.graph?.nodes.find(n => n.id === node.id)
  if (!target) return

  // Answer 节点直接触发聚焦，不弹面板
  if (target.type === 'Answer') {
    emit('focus-answer')
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

  emit('retry', editingNode.value.step_index, editingNode.value.id, editedData)
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
