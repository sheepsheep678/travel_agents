<template>
  <div class="sb-progress-overlay">
    <div class="sb-progress">
      <div class="sb-prog-icon breathe">✒︎</div>
      <h2 class="sb-prog-title">正在为你书写行程…</h2>
      <p class="sb-prog-status">{{ current || '&nbsp;' }}</p>

      <div class="sb-steps">
        <div
          v-for="(s, i) in steps"
          :key="s.label"
          class="sb-step"
          :class="{ done: stepDone[i], active: activeStep === i }"
        >
          <span class="sb-step-ic">{{ stepDone[i] ? '✓' : s.icon }}</span>
          <span class="sb-step-label">{{ s.label }}</span>
        </div>
      </div>

      <div class="sb-bar">
        <div class="sb-bar-fill" :style="{ width: percent + '%' }"></div>
      </div>

      <div v-if="logs.length" class="sb-logs">
        <div v-for="(l, i) in logs" :key="i" class="sb-log" :class="l.level">{{ l.text }}</div>
      </div>

      <button class="sb-cancel" @click="$emit('cancel')">取消生成</button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  percent: number
  current: string
  steps: { icon: string; label: string }[]
  stepDone: boolean[]
  activeStep: number
  logs: { level: 'info' | 'warn' | 'success'; text: string }[]
}>()

defineEmits<{ cancel: [] }>()
</script>

<style scoped>
.sb-progress-overlay {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: var(--paper);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.sb-progress {
  width: min(560px, 100%);
  text-align: center;
}
.sb-prog-icon {
  display: inline-block;
  font-size: 46px;
  line-height: 1;
  color: var(--ink);
}
.sb-prog-title {
  margin: 16px 0 6px;
  font-family: var(--display);
  font-size: 26px;
  color: var(--ink);
  letter-spacing: 0.02em;
}
.sb-prog-status {
  min-height: 20px;
  margin: 0;
  font-size: 13px;
  font-style: italic;
  color: var(--ink-faint);
}

.sb-steps {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin: 26px 0 10px;
}
.sb-step {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  opacity: 0.4;
  transition: opacity 0.3s;
}
.sb-step.active {
  opacity: 1;
}
.sb-step.done {
  opacity: 0.8;
}
.sb-step-ic {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--hairline);
  color: var(--ink-soft);
  font-size: 16px;
}
.sb-step.done .sb-step-ic {
  border-color: var(--ink);
  background: var(--ink);
  color: var(--paper);
}
.sb-step.active .sb-step-ic {
  border-color: var(--ink);
  color: var(--ink);
}
.sb-step-label {
  font-family: var(--display);
  font-size: 13px;
  color: var(--ink-soft);
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.sb-bar {
  height: 2px;
  background: var(--hairline);
  border-radius: 1px;
  margin: 18px 0 14px;
  overflow: hidden;
}
.sb-bar-fill {
  height: 100%;
  background: var(--ink);
  transition: width 0.4s ease;
}

.sb-logs {
  max-height: 140px;
  overflow-y: auto;
  text-align: left;
  padding: 10px 14px;
  border: 1px solid var(--hairline);
  border-radius: 6px;
  margin: 12px 0;
  background: rgba(255, 252, 244, 0.5);
}
.sb-log {
  font-family: var(--font);
  font-size: 12px;
  color: var(--ink-soft);
  padding: 2px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sb-log.warn {
  color: var(--earth);
}
.sb-log.success {
  color: var(--ink);
}

.sb-cancel {
  border: 0;
  background: transparent;
  color: var(--ink-faint);
  font-family: var(--font);
  font-size: 13px;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
  transition: color 0.2s;
}
.sb-cancel:hover {
  color: var(--ink);
}
</style>
