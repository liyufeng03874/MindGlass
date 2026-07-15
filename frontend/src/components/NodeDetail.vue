<template>
  <div class="node-detail">
    <template v-if="type === 'Plan'">
      <div v-if="data.input" class="field">
        <span class="label">输入:</span>
        <span>{{ data.input }}</span>
      </div>
      <div v-if="data.output" class="field">
        <span class="label">思路:</span>
        <span>{{ data.output }}</span>
      </div>
      <div v-if="data.steps?.length" class="field">
        <span class="label">步骤:</span>
        <ul class="steps-list">
          <li v-for="(step, i) in data.steps" :key="i">
            {{ step.tool }}: {{ step.description }}
          </li>
        </ul>
      </div>
    </template>

    <template v-else-if="type === 'ToolCall'">
      <div class="field">
        <span class="label">工具:</span>
        <span class="tool-name">{{ data.tool }}</span>
      </div>
      <div class="field">
        <span class="label">参数:</span>
        <pre class="params">{{ formatJson(data.params) }}</pre>
      </div>
      <div class="field">
        <span class="label">结果:</span>
        <pre class="result">{{ formatJson(data.result) }}</pre>
      </div>
    </template>

    <template v-else-if="type === 'Observe'">
      <div class="field">
        <span class="label">来源:</span>
        <span>{{ data.source }}</span>
      </div>
      <div class="field">
        <span class="label">摘要:</span>
        <pre class="result">{{ data.result_summary }}</pre>
      </div>
    </template>

    <template v-else-if="type === 'Answer'">
      <div class="field answer-field">
        <span class="label">回答:</span>
        <div class="answer-text">{{ data.output }}</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  data: Record<string, any>
  type: string
}>()

function formatJson(obj: any): string {
  if (!obj) return ''
  if (typeof obj === 'string') return obj
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}
</script>

<style scoped>
.node-detail {
  line-height: 1.6;
}

.field {
  margin-bottom: 6px;
}

.label {
  font-weight: 600;
  margin-right: 4px;
}

.tool-name {
  color: #52c41a;
  font-family: monospace;
}

.params, .result {
  background: rgba(0, 0, 0, 0.04);
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 11px;
  max-height: 80px;
  overflow: auto;
  margin-top: 2px;
}

.steps-list {
  margin: 4px 0 0 16px;
  font-size: 11px;
}

.answer-text {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}
</style>
