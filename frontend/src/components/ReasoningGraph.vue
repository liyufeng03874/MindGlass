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
          <label>工具名称</label>
          <input v-model="editForm.tool" class="input-field" />

          <label>参数（JSON）</label>
          <textarea
            v-model="editForm.paramsJson"
            class="textarea-field"
            rows="6"
            placeholder='{"query": "..."}'
          />
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

        <!-- Observe 编辑 -->
        <template v-else-if="editingNode.type === 'Observe'">
          <label>观察结果摘要</label>
          <textarea v-model="editForm.resultSummary" class="textarea-field" rows="6" />
        </template>

        <!-- Answer 只读 -->
        <template v-else-if="editingNode.type === 'Answer'">
          <p class="readonly-hint">回答节点不可编辑，可点击重试重新生成。</p>
        </template>
      </div>

      <div class="panel-footer">
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
import { useReasoningGraph } from '@/composables/useReasoningGraph'
import type { ReasoningGraph, AgentNode } from '@/types/agent'

const props = defineProps<{
  graph: ReasoningGraph | null
  isRunning: boolean
}>()

const emit = defineEmits<{
  (e: 'retry', stepIndex: number, editedData: Record<string, any>): void
}>()

const vueFlowRef = ref(null)
const graphRef = computed(() => props.graph)
const { flowNodes: nodes, flowEdges: edges } = useReasoningGraph(graphRef)

const { fitView } = useVueFlow()

// --- 编辑面板 ---
const editingNode = ref<AgentNode | null>(null)
const editForm = ref<Record<string, any>>({})

function onNodeClick({ node }: { node: { id: string } }) {
  const target = props.graph?.nodes.find(n => n.id === node.id)
  if (!target) return

  editingNode.value = target

  // 初始化表单
  if (target.type === 'ToolCall') {
    editForm.value = {
      tool: target.data.tool || '',
      paramsJson: JSON.stringify(target.data.params || {}, null, 2),
    }
  } else if (target.type === 'Plan') {
    editForm.value = {
      output: target.data.output || '',
      stepsJson: JSON.stringify(target.data.steps || [], null, 2),
    }
  } else if (target.type === 'Observe') {
    editForm.value = {
      resultSummary: target.data.result_summary || '',
    }
  }
}

function closeEditor() {
  editingNode.value = null
  editForm.value = {}
}

async function handleRetry() {
  if (!editingNode.value) return

  let editedData: Record<string, any> = {}

  if (editingNode.value.type === 'ToolCall') {
    try {
      editedData = {
        tool: editForm.value.tool,
        params: JSON.parse(editForm.value.paramsJson),
      }
    } catch {
      alert('参数 JSON 格式错误')
      return
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
  } else if (editingNode.value.type === 'Observe') {
    editedData = {
      result_summary: editForm.value.resultSummary,
    }
  }

  emit('retry', editingNode.value.step_index, editedData)
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
}

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
