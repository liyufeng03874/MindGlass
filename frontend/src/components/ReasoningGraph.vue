<template>
  <div class="reasoning-graph">
    <VueFlow
      v-if="nodes.length > 0"
      :nodes="nodes"
      :edges="edges"
      :default-viewport="{ x: 100, y: 80, zoom: 0.9 }"
      fit-view-on-init
      class="flow-container"
    >
    </VueFlow>

    <div v-else class="empty-state">
      <div class="empty-icon">🧠</div>
      <p>发送问题后，推理过程将在这里展示</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { VueFlow } from '@vue-flow/core'
import { computed } from 'vue'
import { useReasoningGraph } from '@/composables/useReasoningGraph'
import type { ReasoningGraph } from '@/types/agent'

const props = defineProps<{
  graph: ReasoningGraph | null
}>()

const graphRef = computed(() => props.graph)
const { flowNodes: nodes, flowEdges: edges } = useReasoningGraph(graphRef)
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
