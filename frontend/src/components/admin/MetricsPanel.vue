<template>
  <section class="admin-section">
    <header class="admin-section-head">
      <div>
        <h2>运行指标</h2>
        <p>LLM 延迟 / token、缓存命中率、精排熔断、图节点与工具耗时；与 Prometheus 同源。</p>
      </div>
      <div class="admin-section-actions">
        <a v-if="metrics?.prometheus_available" href="/metrics" target="_blank" rel="noreferrer" class="admin-btn admin-btn-ghost">
          Prometheus /metrics
        </a>
        <button class="admin-btn" :disabled="loading || !token" @click="load">
          {{ loading ? '读取中…' : '刷新指标' }}
        </button>
      </div>
    </header>

    <div v-if="!token" class="admin-alert info">请先在上方输入并保存管理端令牌（X-Admin-Token）。</div>
    <div v-if="error" class="admin-alert">{{ error }}</div>

    <template v-if="metrics">
      <div v-if="!metrics.prometheus_available" class="admin-alert info">
        后端未安装 prometheus_client，Prometheus 抓取端点不可用；下方快照仍可用。
      </div>

      <div class="admin-kpi-grid">
        <article class="admin-kpi">
          <p class="admin-kpi-label">LLM 请求</p>
          <p class="admin-kpi-value">{{ metrics.llm.total_requests }}</p>
          <p class="admin-kpi-note">进程启动以来</p>
        </article>
        <article class="admin-kpi">
          <p class="admin-kpi-label">Token 用量</p>
          <p class="admin-kpi-value">{{ metrics.llm.total_tokens }}</p>
          <p class="admin-kpi-note">输入 + 输出（API 或估算）</p>
        </article>
        <article class="admin-kpi">
          <p class="admin-kpi-label">缓存命中率</p>
          <p class="admin-kpi-value">{{ pct(metrics.cache.hit_rate) }}</p>
          <p class="admin-kpi-note">{{ metrics.cache.hits }} hit / {{ metrics.cache.misses }} miss</p>
        </article>
        <article class="admin-kpi">
          <p class="admin-kpi-label">精排熔断</p>
          <p class="admin-kpi-value">{{ metrics.rerank.circuit_breaker }}</p>
          <p class="admin-kpi-note">
            ok {{ metrics.rerank.ok }} · 熔断期跳过 {{ metrics.rerank.circuit_open }}
          </p>
        </article>
        <article class="admin-kpi">
          <p class="admin-kpi-label">快照时间</p>
          <p class="admin-kpi-value" style="font-size: 15px">{{ metrics.generated_at }}</p>
          <p class="admin-kpi-note">{{ metrics.enabled ? 'Prometheus 已启用' : 'Prometheus 导出已关闭' }}</p>
        </article>
      </div>

      <h3 class="admin-subtable-title">LLM 请求状态</h3>
      <ul class="admin-chip-row">
        <li
          v-for="row in metrics.llm.requests"
          :key="`${row.model}-${row.profile}-${row.status}`"
          class="admin-chip"
        >
          {{ row.model }} · {{ row.profile }} · {{ row.status }} · {{ row.count }}
        </li>
        <li v-if="!metrics.llm.requests.length" class="admin-chip">暂无 LLM 请求</li>
      </ul>

      <div class="admin-grid-two" style="margin-top: 20px">
        <div>
          <h3 class="admin-subtable-title">LLM 延迟</h3>
          <div class="admin-table-wrap">
            <table class="admin-table">
              <thead>
                <tr><th>模型</th><th>Profile</th><th>请求数</th><th>平均延迟</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in metrics.llm.latency" :key="`${row.model}-${row.profile}`">
                  <td>{{ row.model }}</td>
                  <td>{{ row.profile }}</td>
                  <td class="num">{{ row.count }}</td>
                  <td class="num">{{ ms(row.avg_ms) }}</td>
                </tr>
                <tr v-if="!metrics.llm.latency.length">
                  <td colspan="4" class="admin-empty">暂无 LLM 调用</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <h3 class="admin-subtable-title">缓存明细</h3>
          <div class="admin-table-wrap">
            <table class="admin-table">
              <thead>
                <tr><th>命名空间</th><th>结果</th><th>次数</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in metrics.cache.by_namespace" :key="`${row.namespace}-${row.result}`">
                  <td>{{ row.namespace }}</td>
                  <td>{{ row.result }}</td>
                  <td class="num">{{ row.count }}</td>
                </tr>
                <tr v-if="!metrics.cache.by_namespace.length">
                  <td colspan="3" class="admin-empty">暂无缓存读写</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <h3 class="admin-subtable-title">节点耗时 Top 12</h3>
      <div v-if="nodeBars.length" class="admin-bars">
        <div v-for="row in nodeBars" :key="row.name" class="admin-bar-row">
          <span class="admin-bar-label" :title="row.name">{{ row.name }}</span>
          <span class="admin-bar-track">
            <span class="admin-bar-fill" :style="{ width: `${barWidth(row.avg_ms)}%` }" />
          </span>
          <span class="admin-bar-value">{{ ms(row.avg_ms) }} · {{ row.count }}</span>
        </div>
      </div>
      <div v-else class="admin-empty">暂无节点耗时（等待下一次对话或行程规划）</div>

      <div class="admin-grid-two" style="margin-top: 20px">
        <div>
          <h3 class="admin-subtable-title">Token 明细</h3>
          <div class="admin-table-wrap">
            <table class="admin-table">
              <thead>
                <tr><th>模型</th><th>Profile</th><th>类型</th><th>来源</th><th>Token</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in metrics.llm.tokens" :key="`${row.model}-${row.profile}-${row.kind}-${row.source}`">
                  <td>{{ row.model }}</td>
                  <td>{{ row.profile }}</td>
                  <td>{{ row.kind }}</td>
                  <td>{{ row.source === 'api' ? 'API' : '估算' }}</td>
                  <td class="num">{{ row.tokens }}</td>
                </tr>
                <tr v-if="!metrics.llm.tokens.length">
                  <td colspan="5" class="admin-empty">暂无 token 数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <h3 class="admin-subtable-title">工具耗时</h3>
          <div class="admin-table-wrap">
            <table class="admin-table">
              <thead>
                <tr><th>工具 / 状态</th><th>次数</th><th>平均</th><th>总耗时</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in metrics.tools" :key="row.name">
                  <td>{{ row.name }}</td>
                  <td class="num">{{ row.count }}</td>
                  <td class="num">{{ ms(row.avg_ms) }}</td>
                  <td class="num">{{ ms(row.total_ms) }}</td>
                </tr>
                <tr v-if="!metrics.tools.length">
                  <td colspan="4" class="admin-empty">暂无工具调用</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <h3 class="admin-subtable-title">HTTP 请求 Top 12</h3>
      <div class="admin-table-wrap">
        <table class="admin-table">
          <thead>
            <tr><th>方法 / 路径 / 状态</th><th>次数</th><th>平均</th><th>总耗时</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in httpRows" :key="row.name">
              <td>{{ row.name }}</td>
              <td class="num">{{ row.count }}</td>
              <td class="num">{{ ms(row.avg_ms) }}</td>
              <td class="num">{{ ms(row.total_ms) }}</td>
            </tr>
            <tr v-if="!httpRows.length">
              <td colspan="4" class="admin-empty">暂无 HTTP 指标</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { AdminMetrics } from '../../types'
import { adminErrorText, fetchAdminMetrics } from '../../services/admin'
import { ms, pct } from './format'

const props = defineProps<{ token: string }>()

const metrics = ref<AdminMetrics | null>(null)
const loading = ref(false)
const error = ref('')

const nodeBars = computed(() =>
  [...(metrics.value?.nodes ?? [])]
    .sort((a, b) => b.avg_ms - a.avg_ms)
    .slice(0, 12),
)
const maxNodeMs = computed(() => Math.max(1, ...nodeBars.value.map((row) => row.avg_ms)))
const httpRows = computed(() =>
  [...(metrics.value?.http ?? [])].sort((a, b) => b.count - a.count).slice(0, 12),
)

function barWidth(value: number): number {
  return Math.max(3, Math.round((value / maxNodeMs.value) * 100))
}

async function load(): Promise<void> {
  if (!props.token) return
  loading.value = true
  error.value = ''
  try {
    const data = await fetchAdminMetrics(props.token)
    metrics.value = data.metrics
  } catch (err) {
    error.value = adminErrorText(err)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.token, (value) => {
  if (value) load()
})
</script>
