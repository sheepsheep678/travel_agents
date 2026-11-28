<template>
  <div class="msg" :class="message.role">
    <div v-if="message.role === 'assistant'" class="msg-avatar">
      <SealMark size="sm" />
    </div>

    <div class="msg-main">
      <div v-if="message.role === 'user'" class="msg-bubble">{{ message.content }}</div>

      <template v-else>
        <div class="msg-text" :class="{ 'is-streaming': message.status === 'streaming' }">
          <MarkdownBody :content="message.content" />
        </div>
        <div v-if="message.status === 'stopped'" class="msg-paused" role="status">
          <span class="msg-paused-ic" aria-hidden="true"><i></i><i></i></span>
          <div class="msg-paused-text">
            <b>已暂停回答</b>
            <span>可调整和补充信息，或换个任务。</span>
          </div>
        </div>
        <p v-if="message.status === 'error'" class="msg-error">{{ message.error || '生成失败，请稍后重试' }}</p>

        <div v-if="message.status === 'done' && message.content" class="msg-actions">
          <button @click="copy">{{ copied ? '已复制' : '复制' }}</button>
          <button v-if="canRegenerate" @click="$emit('regenerate')">重新生成</button>
          <button
            v-if="canPlan"
            class="msg-plan"
            :disabled="planLoading"
            @click="$emit('goPlan')"
          >
            {{ planLoading ? '正在整理对话偏好…' : '用表单生成完整行程 →' }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import SealMark from '../site/SealMark.vue'
import MarkdownBody from './MarkdownBody.vue'
import type { ChatMessage } from '../../types'

const props = defineProps<{
  message: ChatMessage
  canRegenerate?: boolean
  canPlan?: boolean
  planLoading?: boolean
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
  margin-bottom: 30px;
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
  padding: 11px 17px;
  border-radius: 20px 20px 5px 20px;
  background: var(--earth);
  color: #ffffff;
  font-size: 14.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: 0 1px 2px rgba(26, 115, 232, 0.25);
}
.msg-text {
  font-size: 15px;
  line-height: 1.9;
  color: var(--ink);
  word-break: break-word;
}
/* 流式输出光标：贴在 Markdown 最后一个块级元素（或空正文）的行尾 */
.msg-text.is-streaming :deep(.md-body > *:last-child)::after,
.msg-text.is-streaming :deep(.md-body:empty)::after {
  content: '';
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
/* 暂停提示：与普通对话气泡区分（浅黄通告卡片 + 暂停图标） */
.msg-paused {
  display: inline-flex;
  align-items: flex-start;
  gap: 10px;
  max-width: 100%;
  margin-top: 12px;
  padding: 10px 15px 10px 12px;
  border: 1px solid #fde293;
  border-radius: 14px;
  background: #fef7e0;
}
.msg-paused-ic {
  flex: none;
  width: 24px;
  height: 24px;
  margin-top: 1px;
  border-radius: 50%;
  background: #f9ab00;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
}
.msg-paused-ic i {
  width: 3px;
  height: 9px;
  border-radius: 2px;
  background: #ffffff;
}
.msg-paused-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.msg-paused-text b {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
}
.msg-paused-text span {
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-soft);
}
.msg-error {
  margin: 8px 0 0;
  font-size: 12.5px;
  color: var(--seal);
}
.msg-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
}
.msg-actions button {
  padding: 5px 10px;
  border: 0;
  border-radius: 999px;
  background: none;
  font-family: var(--font);
  font-size: 11.5px;
  letter-spacing: 0.01em;
  color: var(--ink-soft);
  cursor: pointer;
  transition: color 0.18s, background 0.18s;
}
.msg-actions button:hover {
  color: var(--blue-dark);
  background: var(--blue-50);
}
.msg-actions .msg-plan {
  padding: 7px 15px;
  border-radius: 999px;
  background: var(--earth);
  color: #ffffff;
  font-weight: 500;
  transition: background 0.18s;
}
.msg-actions .msg-plan:hover {
  background: var(--blue-dark);
  color: #ffffff;
}
.msg-actions .msg-plan:disabled {
  cursor: progress;
  color: var(--ink-faint);
  background: var(--surface-2);
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
