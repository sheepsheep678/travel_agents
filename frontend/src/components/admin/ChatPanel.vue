<template>
  <section class="admin-section">
    <header class="admin-section-head">
      <div>
        <h2>对话评测</h2>
        <p>80 条意图用例：精准 / 模糊 / 危险；规则判定 + 快模型评分。</p>
      </div>
      <div v-if="datasets?.chat" class="admin-section-actions">
        <span class="admin-chip">{{ datasets.chat.count }} 条</span>
        <span class="admin-chip">SHA {{ shortSha(datasets.chat.sha256) }}</span>
      </div>
    </header>

    <div v-if="!token" class="admin-alert info">请先在上方输入并保存管理端令牌（X-Admin-Token）。</div>

    <div class="admin-form-grid">
      <label class="admin-field">
        <span>类别</span>
        <select v-model="form.category" class="admin-select">
          <option value="">全部 80 条</option>
          <option value="precise">precise · 精准 30</option>
          <option value="fuzzy">fuzzy · 模糊 30</option>
          <option value="dangerous">dangerous · 危险 20</option>
        </select>
      </label>
      <label class="admin-field">
        <span>limit</span>
        <input v-model.number="form.limit" type="number" min="0" max="1000" class="admin-input num" />
      </label>
      <label class="admin-field">
        <span>并发</span>
        <input v-model.number="form.concurrency" type="number" min="1" max="10" class="admin-input num" />
      </label>
      <label class="admin-check"><input v-model="form.judge" type="checkbox" /> 启用大模型评分</label>
      <button class="admin-btn" :disabled="running || !token" @click="start">
        {{ running ? '评测运行中…' : '开始对话评测' }}
      </button>
    </div>
    <p class="admin-form-note">
      对话评测在独立 MemorySaver 中运行完整工作流，不依赖 MCP / PostgreSQL；每条用例都会真实调用模型，
      全量 80 条约需数分钟。取消后保留已生成的 token。
    </p>

    <div v-if="datasets?.chat" class="admin-chip-row" style="margin-top: 14px">
      <span v-for="(count, name) in datasets.chat.categories" :key="name" class="admin-chip">
        {{ categoryLabel(name) }} {{ count }}
      </span>
    </div>

    <div v-if="error" class="admin-alert">{{ error }}</div>
    <RunStatus v-if="run" :run="run" @cancel="cancel" />
    <ReportSummary v-if="report" kind="chat" :report="report" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import type { AdminDatasetsResponse, AdminRun } from '../../types'
import { adminErrorText, cancelAdminRun, fetchAdminReport, fetchAdminRun, startAdminEval } from '../../services/admin'
import ReportSummary from './ReportSummary.vue'
import RunStatus from './RunStatus.vue'
import { shortSha } from './format'

const props = defineProps<{
  datasets: AdminDatasetsResponse | null
  token: string
}>()

const CATEGORY_LABELS: Record<string, string> = {
  precise: '精准意图',
  fuzzy: '模糊意图',
  dangerous: '危险意图',
}
function categoryLabel(name: string): string {
  return CATEGORY_LABELS[name] ?? name
}

const form = reactive({
  category: '' as '' | 'precise' | 'fuzzy' | 'dangerous',
  limit: 0,
  concurrency: 3,
  judge: true,
})

const run = ref<AdminRun | null>(null)
const report = ref<Record<string, any> | null>(null)
const error = ref('')
const running = computed(() => run.value?.status === 'running')

let timer: number | undefined

function stopPolling(): void {
  if (timer !== undefined) {
    window.clearTimeout(timer)
    timer = undefined
  }
}

async function loadReport(name: string): Promise<void> {
  try {
    const data = await fetchAdminReport(name, props.token)
    report.value = data.report
  } catch (err) {
    error.value = adminErrorText(err)
  }
}

function schedulePoll(runId: string): void {
  stopPolling()
  timer = window.setTimeout(async () => {
    try {
      const detail = await fetchAdminRun(runId, props.token)
      run.value = detail.run
      if (detail.run.status === 'running') {
        schedulePoll(runId)
      } else if (detail.run.status === 'succeeded' && detail.run.report_name) {
        await loadReport(detail.run.report_name)
      }
    } catch (err) {
      error.value = adminErrorText(err)
    }
  }, 2000)
}

async function start(): Promise<void> {
  error.value = ''
  report.value = null
  try {
    const data = await startAdminEval(
      {
        kind: 'chat',
        dataset: 'base',
        top_k: 10,
        limit: Number(form.limit) || 0,
        rerank: true,
        hyde: 'off',
        rebuild: false,
        hyde_concurrency: 4,
        category: form.category,
        concurrency: Number(form.concurrency) || 3,
        judge: form.judge,
      },
      props.token,
    )
    run.value = data.run
    schedulePoll(data.run.id)
  } catch (err) {
    error.value = adminErrorText(err)
  }
}

async function cancel(runId: string): Promise<void> {
  try {
    const data = await cancelAdminRun(runId, props.token)
    run.value = data.run
    stopPolling()
  } catch (err) {
    error.value = adminErrorText(err)
  }
}

onBeforeUnmount(stopPolling)
</script>
