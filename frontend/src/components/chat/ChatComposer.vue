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
  width: min(800px, calc(100% - 56px));
  margin: 0 auto;
  padding: 16px 0 12px;
}
.composer-box {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 8px 8px 8px 20px;
  border: 1px solid var(--hairline);
  border-radius: 26px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.12), 0 1px 4px rgba(60, 64, 67, 0.08);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.composer-box.focus {
  border-color: #c6dafc;
  box-shadow: 0 1px 6px rgba(32, 33, 36, 0.2), 0 2px 10px rgba(66, 133, 244, 0.1);
}
/* a-textarea 的根 DOM 就是 textarea 本身，class 直接落在它上面，不能用后代选择器 */
.composer-input {
  flex: 1;
  min-width: 0;
  display: block;
  background: transparent;
  border: 0;
  box-shadow: none;
  resize: none;
  font-family: var(--font);
  font-size: 15px;
  /* 固定 24px 行高 + 上下各 8px：单行高度正好 40px，与发送按钮同高，占位文字垂直居中 */
  line-height: 24px;
  min-height: 40px;
  color: var(--ink);
  padding: 8px 0;
}
.composer-input::placeholder {
  color: var(--ink-faint);
}
.composer-btn {
  flex: none;
  height: 40px;
  padding: 0 20px;
  border: 0;
  border-radius: 999px;
  background: var(--earth);
  color: #ffffff;
  font-family: var(--font);
  font-size: 13.5px;
  font-weight: 500;
  letter-spacing: 0.01em;
  cursor: pointer;
  transition: background 0.2s, opacity 0.2s;
}
.composer-btn:hover:not(:disabled) {
  background: var(--blue-dark);
}
.composer-btn:disabled {
  background: var(--surface-2);
  color: var(--ink-faint);
  cursor: default;
}
.composer-btn.stop {
  background: #fce8e6;
  color: var(--seal);
}
.composer-btn.stop:hover {
  background: #fad2cf;
  color: var(--seal);
}
.composer-hint {
  margin: 9px 4px 0;
  font-size: 11px;
  letter-spacing: 0.01em;
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
