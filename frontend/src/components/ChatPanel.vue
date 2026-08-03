<template>
  <div class="chat-panel">
    <div class="messages" ref="messagesRef">
      <!-- 开场白 -->
      <div v-if="messages.length === 0 && initialGreeting" class="message agent greeting">
        <div class="avatar greeting-avatar"><MirrorIcon :size="26" /></div>
        <div class="bubble greeting-bubble">{{ initialGreeting }}</div>
      </div>

      <div
        v-for="(msg, idx) in displayMessages"
        :key="idx"
        :data-msg-index="idx"
        :class="['message', msg.role]"
      >
        <div class="avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
        <div class="bubble" v-if="msg.role === 'agent'" v-html="md.render(msg.content)" :class="{ highlighted: idx === displayMessages.length - 1 && highlightIndex === displayMessages.length - 1 }"></div>
        <div class="bubble" v-else>{{ msg.content }}</div>
      </div>
      <div v-if="loading" class="message agent">
        <div class="avatar">🤖</div>
        <div class="bubble thinking">{{ statusText || '正在规划...' }}</div>
      </div>
    </div>
    <div class="input-area">
      <input
        v-model="inputValue"
        @keyup.enter="handleSend"
        :disabled="disabled"
        placeholder="输入你的问题..."
        class="input"
      />
      <button @click="handleSend" :disabled="disabled || !inputValue.trim()" class="send-btn">
        发送
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import MarkdownIt from 'markdown-it'
import MirrorIcon from './MirrorIcon.vue'

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

const props = defineProps<{
  messages: Array<{ role: 'user' | 'agent', content: string }>
  disabled?: boolean
  initialGreeting?: string
  statusText?: string
  totalElapsed?: string | null
}>()

const emit = defineEmits<{
  send: [query: string]
}>()

const inputValue = ref('')
const highlightIndex = ref<number | null>(null)
const messagesRef = ref<HTMLElement | null>(null)
const loading = computed(() => props.disabled)

/** 将总用时追加到最后一条 agent 消息末尾 */
const displayMessages = computed(() => {
  if (!props.messages.length || !props.totalElapsed) return props.messages
  const lastAgent = [...props.messages].reverse().find(m => m.role === 'agent')
  if (!lastAgent) return props.messages
  const elapsedTag = `\n\n---\n\n*（本次推理耗时 ${props.totalElapsed}）*`
  return props.messages.map((m, i) => {
    if (m === lastAgent && i === props.messages.length - 1) {
      return { ...m, content: m.content + elapsedTag }
    }
    return m
  })
})

watch(() => props.messages.length, async () => {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
})

function highlightLastMessage() {
  if (messagesRef.value && props.messages.length > 0) {
    // 滚动到最后一条
    messagesRef.value.scrollTo({
      top: messagesRef.value.scrollHeight,
      behavior: 'smooth',
    })
    // 高亮最后一条 agent 消息
    highlightIndex.value = props.messages.length - 1
    // 2秒后取消高亮
    setTimeout(() => {
      highlightIndex.value = null
    }, 2000)
  }
}

defineExpose({ highlightLastMessage })

function handleSend() {
  const query = inputValue.value.trim()
  if (!query) return
  emit('send', query)
  inputValue.value = ''
}
</script>

<style scoped>
.chat-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.message {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.message.user {
  flex-direction: row-reverse;
}

.avatar {
  font-size: 24px;
  flex-shrink: 0;
}

.greeting-avatar {
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  filter: drop-shadow(0 0 8px rgba(167, 139, 250, 0.5));
}

.bubble {
  text-align: left;
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

.message.user .bubble {
  background: linear-gradient(135deg, #a78bfa 0%, #8b6ff0 100%);
  color: #fff;
  border-bottom-right-radius: 4px;
  box-shadow: 0 2px 12px rgba(167, 139, 250, 0.25);
}

.message.agent .bubble {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-h);
  border: 1px solid var(--panel-border);
  border-bottom-left-radius: 4px;
  backdrop-filter: blur(8px);
}

/* Agent 消息的 Markdown 样式 */
.message.agent .bubble :deep(h1),
.message.agent .bubble :deep(h2),
.message.agent .bubble :deep(h3),
.message.agent .bubble :deep(h4) {
  margin: 0.8em 0 0.4em;
  font-weight: 600;
  line-height: 1.3;
}
.message.agent .bubble :deep(h1) { font-size: 1.25em; }
.message.agent .bubble :deep(h2) { font-size: 1.15em; }
.message.agent .bubble :deep(h3) { font-size: 1.05em; }
.message.agent .bubble :deep(h1):first-child,
.message.agent .bubble :deep(h2):first-child,
.message.agent .bubble :deep(h3):first-child { margin-top: 0; }

.message.agent .bubble :deep(p) {
  margin: 0.4em 0;
}
.message.agent .bubble :deep(p):first-child { margin-top: 0; }
.message.agent .bubble :deep(p):last-child { margin-bottom: 0; }

.message.agent .bubble :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.5em 0;
  font-size: 0.9em;
}
.message.agent .bubble :deep(th),
.message.agent .bubble :deep(td) {
  border: 1px solid rgba(255, 255, 255, 0.12);
  padding: 6px 10px;
  text-align: left;
}
.message.agent .bubble :deep(th) {
  background: rgba(255, 255, 255, 0.08);
  font-weight: 600;
}
.message.agent .bubble :deep(tr:nth-child(even)) {
  background: rgba(255, 255, 255, 0.02);
}

.message.agent .bubble :deep(blockquote) {
  border-left: 3px solid var(--accent);
  margin: 0.5em 0;
  padding: 0.3em 0.8em;
  color: var(--text);
  background: rgba(167, 139, 250, 0.06);
  border-radius: 0 4px 4px 0;
}

.message.agent .bubble :deep(code) {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-h);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace;
}
.message.agent .bubble :deep(pre) {
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0.5em 0;
}
.message.agent .bubble :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
  font-size: 0.85em;
}

.message.agent .bubble :deep(ul),
.message.agent .bubble :deep(ol) {
  margin: 0.4em 0;
  padding-left: 1.5em;
}
.message.agent .bubble :deep(li) {
  margin: 0.2em 0;
}

.message.agent .bubble :deep(hr) {
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
  margin: 0.8em 0;
}

.message.agent .bubble :deep(a) {
  color: var(--accent);
  text-decoration: none;
}
.message.agent .bubble :deep(a:hover) {
  text-decoration: underline;
}

.elapsed-badge {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-dim);
  font-size: 12px;
  font-family: 'Menlo', 'Monaco', monospace;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--panel-border);
}

.thinking {
  color: var(--text-dim);
  font-style: italic;
}

/* 高亮动画 */
.bubble.highlighted {
  animation: answerHighlight 2s ease;
}

@keyframes answerHighlight {
  0% {
    background: rgba(255, 255, 255, 0.06);
    transform: scale(1);
    box-shadow: none;
  }
  15% {
    transform: scale(1.03);
  }
  30% {
    transform: scale(1);
  }
  10%, 20%, 30%, 40%, 50% {
    background: rgba(167, 139, 250, 0.18);
    box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.35), 0 0 24px rgba(167, 139, 250, 0.25);
  }
  100% {
    background: rgba(255, 255, 255, 0.06);
    transform: scale(1);
    box-shadow: none;
  }
}

.greeting {
  animation: fadeIn 0.5s ease;
}

.greeting-bubble {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border-bottom-left-radius: 4px;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.input-area {
  padding: 12px 16px;
  border-top: 1px solid var(--panel-border);
  display: flex;
  gap: 8px;
}

.input {
  flex: 1;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  font-size: 14px;
  color: var(--text-h);
  outline: none;
  transition: border-color 0.2s;
}

.input::placeholder {
  color: var(--text-dim);
}

.input:focus {
  border-color: var(--accent);
}

.send-btn {
  padding: 8px 16px;
  background: linear-gradient(135deg, #a78bfa 0%, #8b6ff0 100%);
  color: #fff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  box-shadow: 0 2px 12px rgba(167, 139, 250, 0.3);
}

.send-btn:disabled {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-dim);
  box-shadow: none;
  cursor: not-allowed;
}
</style>
