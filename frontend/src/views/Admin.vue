<template>
  <div class="site-page admin-page">
    <PaperWash />
    <SiteHeader active="admin" />

    <main class="site-shell admin-main">
      <section class="admin-hero fade-up">
        <p class="admin-kicker">Evaluation · Observability</p>
        <h1 class="admin-title">评测与可观测性</h1>
        <p class="admin-sub">
          在这里运行检索与对话评测，查看难负例 / 长文档 / 模糊 query 的指标与 HyDE 消融，
          同时观察 LLM 延迟、token 用量、缓存命中率、精排熔断和各节点耗时。
          所有管理端请求都需要 <code>X-Admin-Token</code>。
        </p>
        <div class="admin-token-row">
          <input
            v-model="tokenInput"
            type="password"
            class="admin-input token"
            placeholder="KNOWLEDGE_ADMIN_TOKEN"
            autocomplete="off"
            @keyup.enter="saveToken"
          />
          <button class="admin-btn" @click="saveToken">保存令牌</button>
          <span class="admin-token-state" :class="{ ok: token }">{{ token ? '已配置' : '未配置' }}</span>
        </div>
      </section>

      <div v-if="error" class="admin-alert">{{ error }}</div>

      <section class="admin-section">
        <header class="admin-section-head">
          <div>
            <h2>评测数据集</h2>
            <p>数据集文本冻结；sha256 用于确认测试集未被改动。</p>
          </div>
          <div class="admin-section-actions">
            <button class="admin-btn admin-btn-ghost" :disabled="!token" @click="loadDatasets">刷新数据集</button>
          </div>
        </header>

        <div v-if="!token" class="admin-alert info">请先输入并保存管理端令牌。</div>
        <div v-else-if="datasetsLoading" class="admin-empty">正在读取数据集…</div>
        <div v-else-if="!datasets" class="admin-empty">尚未加载数据集，请检查令牌后刷新。</div>
        <div v-else class="admin-dataset-grid">
          <article v-for="item in datasets.retrieval" :key="item.key" class="admin-dataset-card">
            <h3>{{ datasetLabel(item.key) }}</h3>
            <p>{{ item.count }} 条 query / 文档</p>
            <p>{{ item.file }}</p>
            <p>SHA {{ shortSha(item.sha256) }}</p>
            <ul class="admin-chip-row">
              <li v-for="(count, type) in item.types" :key="type" class="admin-chip">
                {{ typeLabel(String(type)) }} {{ count }}
              </li>
            </ul>
            <details class="admin-sample">
              <summary>查看样例</summary>
              <pre>{{ sampleText(item.samples) }}</pre>
            </details>
          </article>

          <article v-if="datasets.chat" class="admin-dataset-card">
            <h3>对话意图集</h3>
            <p>{{ datasets.chat.count }} 条用例</p>
            <p>{{ datasets.chat.file }}</p>
            <p>SHA {{ shortSha(datasets.chat.sha256) }}</p>
            <ul class="admin-chip-row">
              <li v-for="(count, name) in datasets.chat.categories" :key="name" class="admin-chip">
                {{ categoryLabel(String(name)) }} {{ count }}
              </li>
            </ul>
            <details class="admin-sample">
              <summary>查看样例</summary>
              <pre>{{ sampleText(datasets.chat.samples) }}</pre>
            </details>
          </article>
        </div>
      </section>

      <RetrievalPanel :datasets="datasets" :token="token" />
      <ChatPanel :datasets="datasets" :token="token" />
      <MetricsPanel :token="token" />
      <ReportHistory :token="token" @open="openReport" />

      <section v-if="historyReport" id="history-report" class="admin-section">
        <header class="admin-section-head">
          <div>
            <h2>历史报告</h2>
            <p>{{ historyReport.name }} · {{ historyReport.kind === 'retrieval' ? '检索评测' : '对话评测' }}</p>
          </div>
          <div class="admin-section-actions">
            <button class="admin-btn admin-btn-ghost" @click="historyReport = null">关闭</button>
          </div>
        </header>
        <ReportSummary :kind="historyReport.kind" :report="historyReport.report" />
      </section>
    </main>

    <SiteFooter />
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import PaperWash from '../components/site/PaperWash.vue'
import SiteFooter from '../components/site/SiteFooter.vue'
import SiteHeader from '../components/site/SiteHeader.vue'
import ChatPanel from '../components/admin/ChatPanel.vue'
import MetricsPanel from '../components/admin/MetricsPanel.vue'
import ReportHistory from '../components/admin/ReportHistory.vue'
import ReportSummary from '../components/admin/ReportSummary.vue'
import RetrievalPanel from '../components/admin/RetrievalPanel.vue'
import { usePaperTheme } from '../composables/usePaperTheme'
import { adminErrorText, fetchAdminDatasets, fetchAdminReport, getAdminToken, setAdminToken } from '../services/admin'
import type { AdminDatasetsResponse } from '../types'
import { shortSha } from '../components/admin/format'

usePaperTheme()

const DATASET_LABELS: Record<string, string> = {
  base: 'base · 基础集',
  hard: 'hard · 难负例集',
  all: 'all · 合并集',
}
const TYPE_LABELS: Record<string, string> = {
  base: '基础',
  hard_same_city: '同城不同景点',
  hard_cross_city: '跨城同名',
  long_doc: '长文档',
  fuzzy: '模糊 query',
}
const CATEGORY_LABELS: Record<string, string> = {
  precise: '精准',
  fuzzy: '模糊',
  dangerous: '危险',
}

function datasetLabel(key: string): string {
  return DATASET_LABELS[key] ?? key
}
function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type
}
function categoryLabel(name: string): string {
  return CATEGORY_LABELS[name] ?? name
}

const token = ref(getAdminToken())
const tokenInput = ref(token.value)
const datasets = ref<AdminDatasetsResponse | null>(null)
const datasetsLoading = ref(false)
const error = ref('')
const historyReport = ref<{ name: string; kind: 'retrieval' | 'chat'; report: Record<string, any> } | null>(null)

function sampleText(samples: Array<Record<string, any>> | undefined): string {
  return (samples || [])
    .map((row) => {
      const label = row.type || row.category || 'sample'
      return `#${row.id} [${label}] ${row.query}\n  ${(row.text_preview || '').slice(0, 120)}`
    })
    .join('\n\n')
}

async function loadDatasets(): Promise<void> {
  if (!token.value) return
  error.value = ''
  datasetsLoading.value = true
  try {
    datasets.value = await fetchAdminDatasets(token.value)
  } catch (err) {
    error.value = adminErrorText(err)
  } finally {
    datasetsLoading.value = false
  }
}

function saveToken(): void {
  const value = tokenInput.value.trim()
  setAdminToken(value)
  token.value = value
  error.value = ''
  datasets.value = null
  if (value) loadDatasets()
}

async function openReport(name: string): Promise<void> {
  error.value = ''
  try {
    const data = await fetchAdminReport(name, token.value)
    historyReport.value = { name: data.name, kind: data.kind, report: data.report }
    await nextTick()
    document.getElementById('history-report')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (err) {
    error.value = adminErrorText(err)
  }
}

onMounted(() => {
  if (token.value) loadDatasets()
})
</script>
