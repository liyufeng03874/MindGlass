<template>
  <div class="mindglass">
    <header class="header">
      <h1>🧠 MindGlass</h1>
      <span class="subtitle">可观测多步推理 Agent</span>
      <div class="status-bar">
        <span :class="['status-dot', { active: connected }]"></span>
        <span>{{ status || '就绪' }}</span>
      </div>
    </header>

    <main class="main-content">
      <div class="left-panel">
        <ChatPanel :messages="messages" @send="onSend" />
      </div>
      <div class="right-panel">
        <ReasoningGraph :graph="graph" />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import ChatPanel from './components/ChatPanel.vue'
import ReasoningGraph from './components/ReasoningGraph.vue'
import { useAgentGraph } from './composables/useAgentGraph'

const { graph, status, connected, messages, sendMessage } = useAgentGraph()

function onSend(query: string) {
  sendMessage(query)
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
  gap: 6px;
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
}

.right-panel {
  flex: 1;
  background: #fafafa;
  position: relative;
}
</style>
