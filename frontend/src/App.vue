<template>
  <div class="mindglass">
    <header class="header">
      <h1>🧠 MindGlass</h1>
      <span class="subtitle">可观测多步推理 Agent</span>
      <div class="status-bar">
        <span :class="['status-dot', { active: connected }]"></span>
        <span>{{ status || '就绪' }}</span>
        <button
          v-if="graph.nodes.length === 0"
          class="toggle-graph-btn"
          @click="loadTestData"
        >
          📦 加载测试数据
        </button>
        <button
          v-else
          class="toggle-graph-btn"
          @click="showGraph = !showGraph"
        >
          {{ showGraph ? '👁️ 隐藏思维' : '💡 思维可视化' }}
        </button>
      </div>
    </header>

    <main class="main-content">
      <div :class="['left-panel', { full: !showGraph }]">
        <ChatPanel
          :messages="messages"
          :disabled="isRunning"
          @send="onSend"
          :initialGreeting="initialGreeting"
        />
      </div>
      <transition name="slide">
        <div v-if="showGraph" class="right-panel">
          <ReasoningGraph :graph="graph" :isRunning="isRunning" @retry="onRetry" />
        </div>
      </transition>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import ChatPanel from './components/ChatPanel.vue'
import ReasoningGraph from './components/ReasoningGraph.vue'
import { useAgentGraph } from './composables/useAgentGraph'

const { graph, status, connected, messages, isRunning, sendMessage, retryFrom } = useAgentGraph()

const showGraph = ref(false)
const initialGreeting = '你好，我是 MindGlass 🧠\n\n我可以帮你拆解复杂问题、调用工具搜索、生成结构化回答。试试问我点什么吧～'

  function onSend(query: string) {
  sendMessage(query)
  // 第一次发送消息时，展示右侧推理面板
  if (graph.value.nodes.length === 0 && !showGraph.value) {
    showGraph.value = true
  }
}

function onRetry(stepIndex: number, editedData: Record<string, any>) {
  retryFrom(stepIndex, editedData)
}

function loadTestData() {
  // 调用后端加载 demo_6 数据
  fetch('http://localhost:8002/api/load-demo', { method: 'POST' })
    .then(res => res.json())
    .then(() => {
      // 加载完成后获取图数据
      return fetch('http://localhost:8002/api/graph')
    })
    .then(res => res.json())
    .then(data => {
      graph.value = data
      showGraph.value = true
      status.value = '📦 已加载 demo_6 测试数据'
    })
    .catch(() => {
      status.value = '❌ 加载测试数据失败'
    })
}
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #f5f7fa;
  color: #333;
}

.mindglass {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  background: #fff;
  padding: 12px 24px;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  gap: 16px;
}

.header h1 {
  font-size: 20px;
  color: #1a1a2e;
}

.subtitle {
  font-size: 13px;
  color: #888;
}

.status-bar {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
  color: #666;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ccc;
}

.status-dot.active {
  background: #52c41a;
  animation: pulse 1.5s infinite;
}

.toggle-graph-btn {
  padding: 4px 12px;
  background: #f0f0f0;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: #555;
  transition: all 0.2s;
}

.toggle-graph-btn:hover {
  background: #e8e8e8;
  color: #333;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.main-content {
  flex: 1;
  display: flex;
  gap: 0;
  overflow: hidden;
}

.left-panel {
  width: 400px;
  min-width: 320px;
  border-right: 1px solid #e8e8e8;
  background: #fff;
  transition: width 0.3s ease;
}

.left-panel.full {
  width: 100%;
  border-right: none;
}

.right-panel {
  flex: 1;
  background: #fafafa;
  position: relative;
}

/* 右侧面板滑入动画 */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.3s ease;
}

.slide-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.slide-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
