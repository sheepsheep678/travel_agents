<template>
  <div class="composer">
    <div class="composer-box" :class="{ focus: focused }">
      <a-textarea
        v-model:value="text"
        class="composer-input"
        :auto-size="{ minRows: 1, maxRows: 6 }"
        :bordered="false"
        placeholder="说说你想去哪儿、玩几天，或者直接问一个问题…"
        @focus="focused = true"
        @blur="focused = false"
        @keydown="onKeydown"
      />
      <button v-if="streaming" class="composer-btn stop" @click="$emit('stop')">停止</button>
      <button v-else class="composer-btn" :disabled="!text.trim()" @click="submit">发送</button>
    </div>
    <p class="composer-hint">Enter 发送 · Shift + Enter 换行 · 回复由 AI 生成，请核对后再出行</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ streaming?: boolean }>()
const emit = defineEmits<{ send: [text: string]; stop: [] }>()

const text = ref('')
const focused = ref(false)

function submit() {
  const value = text.value.trim()
  if (!value || props.streaming) return
  emit('send', value)
  text.value = ''
}

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter' || e.shiftKey) return
  // 中文输入法选词回车不能触发发送
  if (e.isComposing) return
  e.preventDefault()
  submit()
}
</script>

<style scoped>
.composer {
  width: min(760px, calc(100% - 56px));
  margin: 0 auto;
  padding: 14px 0 10px;
}
.composer-box {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 9px 10px 9px 14px;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  background: rgba(255, 252, 244, 0.72);
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
}
.composer-box.focus {
  border-color: rgba(43, 39, 33, 0.42);
  background: rgba(255, 252, 244, 0.95);
  box-shadow: 0 10px 26px -22px rgba(43, 39, 33, 0.7);
}
.composer-input {
  flex: 1;
  min-width: 0;
}
.composer-input :deep(textarea) {
  background: transparent;
  border: 0;
  box-shadow: none;
  resize: none;
  font-family: var(--font);
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink);
  padding: 4px 0;
}
.composer-input :deep(textarea::placeholder) {
  color: var(--ink-faint);
}
.composer-btn {
  flex: none;
  height: 36px;
  padding: 0 18px;
  border: 0;
  border-radius: 3px;
  background: var(--ink);
  color: var(--paper);
  font-family: var(--font);
  font-size: 13px;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition: background 0.2s, opacity 0.2s;
}
.composer-btn:hover:not(:disabled) {
  background: var(--earth);
  color: #fff;
}
.composer-btn:disabled {
  opacity: 0.3;
  cursor: default;
}
.composer-btn.stop {
  background: transparent;
  border: 1px solid var(--hairline);
  color: var(--ink);
}
.composer-btn.stop:hover {
  border-color: var(--seal);
  color: var(--seal);
  background: transparent;
}
.composer-hint {
  margin: 8px 2px 0;
  font-size: 10.5px;
  letter-spacing: 0.02em;
  color: var(--ink-faint);
}

@media (max-width: 560px) {
  .composer {
    width: calc(100% - 28px);
    padding: 10px 0 8px;
  }
  .composer-hint {
    display: none;
  }
}
</style>
