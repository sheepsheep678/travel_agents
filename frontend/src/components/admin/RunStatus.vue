<template>
  <div class="admin-run">
    <div class="admin-run-head">
      <span class="admin-status" :class="run.status">{{ statusLabel }}</span>
      <span class="admin-run-meta">
        run {{ run.id }} · 开始 {{ run.started_at }}
        <template v-if="run.finished_at"> · 结束 {{ run.finished_at }}</template>
        <template v-if="run.returncode !== null && run.returncode !== undefined">
          · 退出码 {{ run.returncode }}
        </template>
      </span>
      <button
        v-if="run.status === 'running'"
        class="admin-btn admin-btn-danger"
        @click="$emit('cancel', run.id)"
      >
        取消评测
      </button>
    </div>

    <p v-if="run.error" class="admin-alert">{{ run.error }}</p>
    <pre v-if="run.log.length" class="admin-log">{{ run.log.join('\n') }}</pre>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AdminRun } from '../../types'

const props = defineProps<{ run: AdminRun }>()
defineEmits<{ (e: 'cancel', runId: string): void }>()

const LABELS: Record<string, string> = {
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const statusLabel = computed(() => LABELS[props.run.status] ?? props.run.status)
</script>
