<template>
  <div class="msg" :class="message.role">
    <div v-if="message.role === 'assistant'" class="msg-avatar">
      <SealMark size="sm" />
    </div>

    <div class="msg-main">
      <div v-if="message.role === 'user'" class="msg-bubble">{{ message.content }}</div>

      <template v-else>
        <div class="msg-text">
          {{ message.content }}<span v-if="message.status === 'streaming'" class="caret" aria-hidden="true"></span>
        </div>
        <p v-if="message.status === 'stopped'" class="msg-note">已停止生成</p>
        <p v-if="message.status === 'error'" class="msg-error">{{ message.error || '生成失败，请稍后重试' }}</p>

        <div v-if="message.status === 'done' && message.content" class="msg-actions">
          <button @click="copy">{{ copied ? '已复制' : '复制' }}</button>
          <button v-if="canRegenerate" @click="$emit('regenerate')">重新生成</button>
          <button v-if="canPlan" class="msg-plan" @click="$emit('goPlan')">用表单生成完整行程 →</button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import SealMark from '../site/SealMark.vue'
import type { ChatMessage } from '../../types'

const props = defineProps<{
  message: ChatMessage
  canRegenerate?: boolean
  canPlan?: boolean
}>()

defineEmits<{ regenerate: []; goPlan: [] }>()

const copied = ref(false)
let copyTimer: number | undefined

onUnmounted(() => {
  if (copyTimer) window.clearTimeout(copyTimer)
})

async function copy() {
  const text = props.message.content
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      legacyCopy(text)
    }
    copied.value = true
    if (copyTimer) window.clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => (copied.value = false), 1600)
  } catch {
    /* 剪贴板不可用时静默失败 */
  }
}

function legacyCopy(text: string) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
}
</script>

<style scoped>
.msg {
  display: flex;
  gap: 14px;
  margin-bottom: 28px;
}
.msg.user {
  justify-content: flex-end;
  margin-left: 18%;
}
.msg.assistant {
  margin-right: 8%;
}
.msg-avatar {
  flex: none;
  padding-top: 2px;
}
.msg-main {
  min-width: 0;
  max-width: 100%;
}
.msg-bubble {
  padding: 12px 16px;
  border-radius: 10px 10px 2px 10px;
  background: var(--ink);
  color: var(--paper);
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-text {
  font-size: 14.5px;
  line-height: 1.95;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
}
.caret {
  display: inline-block;
  width: 2px;
  height: 1.05em;
  margin-left: 3px;
  vertical-align: -2px;
  background: var(--earth);
  animation: caret-blink 1s steps(1) infinite;
}
@keyframes caret-blink {
  50% { opacity: 0; }
}
.msg-note {
  margin: 8px 0 0;
  font-size: 11px;
  font-style: italic;
  color: var(--ink-faint);
}
.msg-error {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--seal);
}
.msg-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  margin-top: 12px;
}
.msg-actions button {
  padding: 0;
  border: 0;
  background: none;
  font-family: var(--font);
  font-size: 11px;
  letter-spacing: 0.03em;
  color: var(--ink-faint);
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
  transition: color 0.2s;
}
.msg-actions button:hover {
  color: var(--ink);
}
.msg-actions .msg-plan {
  padding: 6px 12px;
  border: 1px solid var(--hairline);
  border-radius: 2px;
  color: var(--ink);
  text-decoration: none;
  transition: border-color 0.2s, background 0.2s;
}
.msg-actions .msg-plan:hover {
  border-color: var(--ink);
  background: rgba(255, 252, 244, 0.7);
}

@media (max-width: 560px) {
  .msg.user {
    margin-left: 8%;
  }
  .msg.assistant {
    margin-right: 0;
  }
}
</style>
