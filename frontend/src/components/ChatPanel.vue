<template>
  <div class="chat-panel">
    <div class="messages" ref="messagesRef">
      <!-- 开场白 -->
      <div v-if="messages.length === 0 && initialGreeting" class="message agent greeting">
        <div class="avatar">🧠</div>
        <div class="bubble greeting-bubble">{{ initialGreeting }}</div>
      </div>

      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        :class="['message', msg.role]"
      >
        <div class="avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
        <div class="bubble">{{ msg.content }}</div>
      </div>
      <div v-if="loading" class="message agent">
        <div class="avatar">🤖</div>
        <div class="bubble thinking">正在思考...</div>
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

const props = defineProps<{
  messages: Array<{ role: 'user' | 'agent', content: string }>
  disabled?: boolean
  initialGreeting?: string
}>()

const emit = defineEmits<{
  send: [query: string]
}>()

const inputValue = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const loading = computed(() => props.disabled)

watch(() => props.messages.length, async () => {
  await nextTick()
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
})

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

.bubble {
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

.message.user .bubble {
  background: #1677ff;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message.agent .bubble {
  background: #f0f0f0;
  color: #333;
  border-bottom-left-radius: 4px;
}

.thinking {
  color: #999;
  font-style: italic;
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
  border-top: 1px solid #e8e8e8;
  display: flex;
  gap: 8px;
}

.input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
}

.input:focus {
  border-color: #1677ff;
}

.send-btn {
  padding: 8px 16px;
  background: #1677ff;
  color: #fff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
}

.send-btn:disabled {
  background: #d9d9d9;
  cursor: not-allowed;
}
</style>
