<template>
  <section class="admin-section">
    <header class="admin-section-head">
      <div>
        <h2>检索评测</h2>
        <p>稠密 / BM25 / 混合检索，难负例、长文档、模糊 query，含 nDCG@10 与 HyDE 消融。</p>
      </div>
      <div class="admin-section-actions">
        <span v-if="selected" class="admin-chip">{{ selected.count }} 条</span>
        <span v-if="selected" class="admin-chip">SHA {{ shortSha(selected.sha256) }}</span>
      </div>
    </header>

    <div v-if="!token" class="admin-alert info">请先在上方输入并保存管理端令牌（X-Admin-Token）。</div>

    <div class="admin-form-grid">
      <label class="admin-field">
        <span>数据集</span>
        <select v-model="form.dataset" class="admin-select">
          <option value="base">base · 基础 100 对</option>
          <option value="hard">hard · 难负例 48 条</option>
          <option value="all">all · 合并 148 条</option>
        </select>
      </label>
      <label class="admin-field">
        <span>top_k</span>
        <input v-model.number="form.top_k" type="number" min="1" max="50" class="admin-input num" />
      </label>
      <label class="admin-field">
        <span>limit</span>
        <input v-model.number="form.limit" type="number" min="0" max="1000" class="admin-input num" />
      </label>
      <label class="admin-field">
        <span>HyDE</span>
        <select v-model="form.hyde" class="admin-select">
          <option value="off">off · 只用原问句</option>
          <option value="both">both · 生成消融表</option>
          <option value="on">on · 只跑 HyDE</option>
        </select>
      </label>
      <label class="admin-field">
        <span>HyDE 并发</span>
        <input v-model.number="form.hyde_concurrency" type="number" min="1" max="16" class="admin-input num" />
      </label>
      <label class="admin-check"><input v-model="form.rerank" type="checkbox" /> Cross-Encoder 精排</label>
      <label class="admin-check"><input v-model="form.rebuild" type="checkbox" /> 强制重建评测集合</label>
      <button
        class="admin-btn"
        :disabled="running || !token"
        @click="start"
      >
        {{ running ? '评测运行中…' : '开始检索评测' }}
      </button>
    </div>
    <p class="admin-form-note">
      limit=0 表示跑全部 query。hard/all 会启用城市过滤；勾选「强制重建」会删除并重建
      <code>retrieval_eval*</code> 评测集合（不影响生产知识库）。HyDE 会为每条 query 调用一次快模型。
    </p>

    <div v-if="selected" class="admin-chip-row" style="margin-top: 14px">
      <span v-for="(count, type) in selected.types" :key="type" class="admin-chip">
        {{ typeLabel(type) }} {{ count }}
      </span>
    </div>

    <div v-if="error" class="admin-alert">{{ error }}</div>
    <RunStatus v-if="run" :run="run" @cancel="cancel" />
    <ReportSummary v-if="report" kind="retrieval" :report="report" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import type { AdminDatasetsResponse, AdminRun, RetrievalDatasetKey } from '../../types'
import { adminErrorText, cancelAdminRun, fetchAdminReport, fetchAdminRun, startAdminEval } from '../../services/admin'
import ReportSummary from './ReportSummary.vue'
import RunStatus from './RunStatus.vue'
import { shortSha } from './format'

const props = defineProps<{
  datasets: AdminDatasetsResponse | null
  token: string
}>()

const TYPE_LABELS: Record<string, string> = {
  base: '基础集',
  hard_same_city: '同城不同景点',
  hard_cross_city: '跨城同名景点',
  long_doc: '长文档',
  fuzzy: '模糊 query',
}
function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type
}

const form = reactive({
  dataset: 'hard' as RetrievalDatasetKey,
  top_k: 10,
  limit: 0,
  rerank: true,
  hyde: 'both' as 'off' | 'on' | 'both',
  rebuild: false,
  hyde_concurrency: 4,
})

const run = ref<AdminRun | null>(null)
const report = ref<Record<string, any> | null>(null)
const error = ref('')
const running = computed(() => run.value?.status === 'running')

const selected = computed(() => props.datasets?.retrieval.find((item) => item.key === form.dataset))

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
  }, 1600)
}

async function start(): Promise<void> {
  error.value = ''
  report.value = null
  try {
    const data = await startAdminEval(
      {
        kind: 'retrieval',
        dataset: form.dataset,
        top_k: Number(form.top_k) || 10,
        limit: Number(form.limit) || 0,
        rerank: form.rerank,
        hyde: form.hyde,
        rebuild: form.rebuild,
        hyde_concurrency: Number(form.hyde_concurrency) || 4,
        category: '',
        concurrency: 3,
        judge: true,
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
