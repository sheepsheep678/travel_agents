<template>
  <div class="sb-progress-overlay">
    <div class="sb-progress">
      <div class="sb-prog-spinner" aria-hidden="true"></div>
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

      <button class="sb-cancel" @click="$emit('cancel')">取消规划</button>
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
  background:
    radial-gradient(760px 460px at 50% 0%, rgba(66, 133, 244, 0.08), transparent 66%),
    var(--surface);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.sb-progress {
  width: min(620px, 100%);
  padding: 40px 40px 30px;
  background: #ffffff;
  border: 1px solid var(--hairline);
  border-radius: 28px;
  box-shadow: var(--shadow-2);
  text-align: center;
}
.sb-prog-spinner {
  width: 44px;
  height: 44px;
  margin: 0 auto;
  border: 4px solid var(--surface-2);
  border-top-color: var(--earth);
  border-radius: 50%;
  animation: sb-spin 0.9s linear infinite;
}
@keyframes sb-spin {
  to { transform: rotate(360deg); }
}
.sb-prog-title {
  margin: 22px 0 6px;
  font-family: var(--display);
  font-weight: 500;
  font-size: 26px;
  color: var(--ink);
  letter-spacing: 0.01em;
}
.sb-prog-status {
  min-height: 20px;
  margin: 0;
  font-size: 14px;
  color: var(--ink-soft);
}

.sb-steps {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin: 30px 0 14px;
}
.sb-step {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
  opacity: 0.5;
  transition: opacity 0.3s;
}
.sb-step.active {
  opacity: 1;
}
.sb-step.done {
  opacity: 1;
}
.sb-step-ic {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--ink-soft);
  font-size: 14px;
  font-weight: 500;
  transition: background 0.3s, color 0.3s, box-shadow 0.3s;
}
.sb-step.done .sb-step-ic {
  background: var(--earth);
  color: #ffffff;
}
.sb-step.active .sb-step-ic {
  background: #ffffff;
  color: var(--blue-dark);
  box-shadow: inset 0 0 0 2px var(--earth);
}
.sb-step-label {
  font-family: var(--display);
  font-size: 13px;
  color: var(--ink-soft);
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.sb-step.active .sb-step-label {
  color: var(--ink);
  font-weight: 500;
}

.sb-bar {
  height: 4px;
  background: #e8eaed;
  border-radius: 999px;
  margin: 20px 0 16px;
  overflow: hidden;
}
.sb-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--earth);
  transition: width 0.4s ease;
}

.sb-logs {
  max-height: 150px;
  overflow-y: auto;
  text-align: left;
  padding: 12px 14px;
  border: 1px solid var(--hairline);
  border-radius: 12px;
  margin: 14px 0;
  background: var(--surface);
}
.sb-log {
  font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
  font-size: 11.5px;
  color: var(--ink-soft);
  padding: 2px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sb-log.warn {
  color: #b06000;
}
.sb-log.success {
  color: var(--green);
}

.sb-cancel {
  border: 0;
  background: transparent;
  color: var(--earth);
  font-family: var(--font);
  font-size: 13px;
  font-weight: 500;
  padding: 8px 14px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.2s;
}
.sb-cancel:hover {
  background: var(--blue-50);
}

@media (max-width: 560px) {
  .sb-progress {
    padding: 30px 20px 22px;
    border-radius: 22px;
  }
  .sb-step-label {
    font-size: 11.5px;
  }
  .sb-step-ic {
    width: 38px;
    height: 38px;
  }
}
</style>
