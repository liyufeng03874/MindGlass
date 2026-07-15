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
    />

    <div v-else class="empty-state">
      <div class="empty-icon">🧠</div>
      <p>发送问题后，推理过程将在这里展示</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { computed, ref, watch } from 'vue'
import { useReasoningGraph } from '@/composables/useReasoningGraph'
import type { ReasoningGraph } from '@/types/agent'

const props = defineProps<{
  graph: ReasoningGraph | null
}>()

const vueFlowRef = ref(null)
const graphRef = computed(() => props.graph)
const { flowNodes: nodes, flowEdges: edges } = useReasoningGraph(graphRef)

const { fitView } = useVueFlow()

// 监听节点数量变化，当有 Answer 节点时自动适配视图
watch(
  () => nodes.value.length,
  (newLen, oldLen) => {
    if (newLen > oldLen && newLen > 0) {
      // 检查最后一个节点是否是 Answer
      const lastNode = nodes.value[nodes.value.length - 1]
      if (lastNode?.data?.type === 'Answer') {
        // 延迟一下让 Vue Flow 渲染完成
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
</style>
