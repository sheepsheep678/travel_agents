<template>
  <!-- ==================== 检索评测 ==================== -->
  <div v-if="kind === 'retrieval'" class="admin-report">
    <div class="admin-kpi-grid">
      <article class="admin-kpi">
        <p class="admin-kpi-label">数据集 / 条数</p>
        <p class="admin-kpi-value">{{ report.dataset || '—' }} · {{ report.queries ?? '—' }}</p>
        <p class="admin-kpi-note">collection {{ report.collection || '—' }}</p>
      </article>
      <article class="admin-kpi">
        <p class="admin-kpi-label">Recall@1 / @5</p>
        <p class="admin-kpi-value">{{ pct(primaryMetrics['recall@1']) }} / {{ pct(primaryMetrics['recall@5']) }}</p>
        <p class="admin-kpi-note">主结果：{{ modeLabel(primary.mode || 'hybrid') }}</p>
      </article>
      <article class="admin-kpi">
        <p class="admin-kpi-label">MRR / nDCG@10</p>
        <p class="admin-kpi-value">{{ num(metric(primaryMetrics, 'mrr@'), 3) }} / {{ num(metric(primaryMetrics, 'ndcg@'), 3) }}</p>
        <p class="admin-kpi-note">top_k={{ report.top_k ?? 10 }}，rerank={{ report.rerank ? '开' : '关' }}</p>
      </article>
      <article class="admin-kpi">
        <p class="admin-kpi-label">P50 / P95 延迟</p>
        <p class="admin-kpi-value">{{ ms(primaryMetrics?.latency_ms?.p50) }} / {{ ms(primaryMetrics?.latency_ms?.p95) }}</p>
        <p class="admin-kpi-note">HyDE={{ report.hyde_mode || 'off' }}，总耗时 {{ seconds(report.duration_seconds) }}</p>
      </article>
      <article class="admin-kpi">
        <p class="admin-kpi-label">估算成本（可配置单价）</p>
        <p class="admin-kpi-value">{{ cny(usage.estimated_cost_cny) }}</p>
        <p class="admin-kpi-note">
          embedding≈{{ usage.embedding_tokens ?? 0 }} tok · rerank≈{{ usage.rerank_documents ?? 0 }} docs
          <template v-if="usage.hyde_calls">
            · HyDE {{ usage.hyde_calls }} 次（P95 {{ ms(usage.hyde_latency_ms?.p95) }}）
          </template>
        </p>
      </article>
    </div>

    <p class="admin-sub" style="margin-top: 14px">
      生成于 {{ report.generated_at || '—' }} · 入库 {{ report.ingestion || '—' }} ·
      SHA {{ shortSha(report.dataset_sha256) }} ·
      {{ usage.note || '' }}
    </p>

    <h3 class="admin-subtable-title">HyDE 消融表</h3>
    <div class="admin-table-wrap">
      <table class="admin-table">
        <thead>
          <tr>
            <th>检索方式</th>
            <th>HyDE</th>
            <th>Recall@1</th>
            <th>Recall@5</th>
            <th>MRR@10</th>
            <th>nDCG@10</th>
            <th>P50</th>
            <th>P95</th>
            <th>估算成本</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ablationRows" :key="`${row.mode}-${row.hyde}`">
            <td>{{ modeLabel(row.mode) }}</td>
            <td>{{ row.hyde ? '开' : '关' }}</td>
            <td class="num">{{ pct(row['recall@1']) }}</td>
            <td class="num">{{ pct(row['recall@5']) }}</td>
            <td class="num">{{ num(metric(row, 'mrr@'), 3) }}</td>
            <td class="num">{{ num(metric(row, 'ndcg@'), 3) }}</td>
            <td class="num">{{ ms(row.latency_ms?.p50) }}</td>
            <td class="num">{{ ms(row.latency_ms?.p95) }}</td>
            <td class="num">{{ cny(row.usage?.estimated_cost_cny) }}</td>
          </tr>
          <tr v-if="!ablationRows.length">
            <td colspan="9" class="admin-empty">报告里没有消融数据</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3 class="admin-subtable-title">分类型指标（主结果）</h3>
    <div class="admin-table-wrap">
      <table class="admin-table">
        <thead>
          <tr>
            <th>数据类型</th>
            <th>条数</th>
            <th>Recall@1</th>
            <th>Recall@5</th>
            <th>MRR@10</th>
            <th>nDCG@10</th>
            <th>P95</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in byTypeRows" :key="row.type">
            <td>{{ typeLabel(row.type) }}</td>
            <td class="num">{{ row.count }}</td>
            <td class="num">{{ pct(row['recall@1']) }}</td>
            <td class="num">{{ pct(row['recall@5']) }}</td>
            <td class="num">{{ num(metric(row, 'mrr@'), 3) }}</td>
            <td class="num">{{ num(metric(row, 'ndcg@'), 3) }}</td>
            <td class="num">{{ ms(row.latency_ms?.p95) }}</td>
          </tr>
          <tr v-if="!byTypeRows.length">
            <td colspan="7" class="admin-empty">暂无分类型数据</td>
          </tr>
        </tbody>
      </table>
    </div>

    <template v-if="cityCheck">
      <h3 class="admin-subtable-title">跨城同名景点 · 城市过滤校验（不过滤诊断）</h3>
      <div class="admin-kpi-grid">
        <article class="admin-kpi">
          <p class="admin-kpi-label">跨城 query 数</p>
          <p class="admin-kpi-value">{{ cityCheck?.queries ?? '—' }}</p>
        </article>
        <article class="admin-kpi">
          <p class="admin-kpi-label">错误城市压过目标</p>
          <p class="admin-kpi-value">{{ cityCheck?.wrong_city_outranks ?? '—' }}</p>
          <p class="admin-kpi-note">比例 {{ pct(cityCheck?.wrong_city_rate) }}</p>
        </article>
        <article class="admin-kpi">
          <p class="admin-kpi-label">目标命中@k</p>
          <p class="admin-kpi-value">{{ pct(cityCheck?.['target_hit@k']) }}</p>
        </article>
      </div>
    </template>

    <h3 class="admin-subtable-title">
      逐条明细
      <button class="admin-btn admin-btn-ghost" style="margin-left: 10px" @click="showAllDetails = !showAllDetails">
        {{ showAllDetails ? '收起' : `展开全部 ${detailRows.length} 条` }}
      </button>
    </h3>
    <div class="admin-table-wrap">
      <table class="admin-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>类型</th>
            <th>Query</th>
            <th>名次</th>
            <th>nDCG@10</th>
            <th>延迟</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in visibleDetails" :key="row.id">
            <td>{{ row.id }}</td>
            <td>{{ typeLabel(row.type) }}</td>
            <td class="wrap">{{ row.query }}</td>
            <td class="num" :class="row.rank ? 'admin-pass' : 'admin-fail'">{{ row.rank ?? 'miss' }}</td>
            <td class="num">{{ num(metric(row, 'ndcg@'), 3) }}</td>
            <td class="num">{{ ms(row.latency_ms) }}</td>
          </tr>
          <tr v-if="!detailRows.length">
            <td colspan="6" class="admin-empty">暂无明细</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- ==================== 对话评测 ==================== -->
  <div v-else-if="kind === 'chat'" class="admin-report">
    <div class="admin-kpi-grid">
      <article class="admin-kpi">
        <p class="admin-kpi-label">用例总数</p>
        <p class="admin-kpi-value">{{ overall.total ?? '—' }}</p>
        <p class="admin-kpi-note">数据集 {{ report.dataset || '—' }}，模型 {{ report.model || '—' }}</p>
      </article>
      <article class="admin-kpi">
        <p class="admin-kpi-label">规则通过率</p>
        <p class="admin-kpi-value">{{ pct(overall.rule_pass_rate) }}</p>
        <p class="admin-kpi-note">{{ overall.rule_pass ?? 0 }} / {{ overall.total ?? 0 }}</p>
      </article>
      <article class="admin-kpi">
        <p class="admin-kpi-label">意图准确率</p>
        <p class="admin-kpi-value">{{ pct(overall.intent_ok_rate) }}</p>
        <p class="admin-kpi-note">大模型评分</p>
      </article>
      <article class="admin-kpi">
        <p class="admin-kpi-label">安全合规率</p>
        <p class="admin-kpi-value">{{ pct(overall.safety_ok_rate) }}</p>
      </article>
      <article class="admin-kpi">
        <p class="admin-kpi-label">平均质量分</p>
        <p class="admin-kpi-value">{{ num(overall.avg_quality, 1) }}</p>
        <p class="admin-kpi-note">总耗时 {{ seconds(report.duration_seconds) }}</p>
      </article>
    </div>

    <p class="admin-sub" style="margin-top: 14px">
      生成于 {{ report.generated_at || '—' }} · SHA {{ shortSha(report.dataset_sha256) }}
    </p>

    <h3 class="admin-subtable-title">分类别指标</h3>
    <div class="admin-table-wrap">
      <table class="admin-table">
        <thead>
          <tr>
            <th>类别</th>
            <th>条数</th>
            <th>规则通过率</th>
            <th>意图准确率</th>
            <th>安全合规率</th>
            <th>平均质量</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, name) in byCategory" :key="name">
            <td>{{ categoryLabel(name) }}</td>
            <td class="num">{{ row.total }}</td>
            <td class="num">{{ pct(row.rule_pass_rate) }}</td>
            <td class="num">{{ pct(row.intent_ok_rate) }}</td>
            <td class="num">{{ pct(row.safety_ok_rate) }}</td>
            <td class="num">{{ num(row.avg_quality, 1) }}</td>
          </tr>
          <tr v-if="!Object.keys(byCategory).length">
            <td colspan="6" class="admin-empty">暂无分类数据</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3 class="admin-subtable-title">实际意图分布</h3>
    <ul class="admin-chip-row">
      <li v-for="(count, name) in actualIntents" :key="name" class="admin-chip">
        {{ name }} · {{ count }}
      </li>
    </ul>

    <h3 class="admin-subtable-title">
      逐条用例
      <button class="admin-btn admin-btn-ghost" style="margin-left: 10px" @click="showAllDetails = !showAllDetails">
        {{ showAllDetails ? '收起' : `展开全部 ${caseRows.length} 条` }}
      </button>
    </h3>
    <div class="admin-table-wrap">
      <table class="admin-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>类别</th>
            <th>用户输入</th>
            <th>实际路由</th>
            <th>规则</th>
            <th>意图</th>
            <th>安全</th>
            <th>质量</th>
            <th>评委理由</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in visibleCases" :key="row.id">
            <td>{{ row.id }}</td>
            <td>{{ categoryLabel(row.category) }}</td>
            <td class="wrap">{{ row.query }}</td>
            <td>{{ row.actual_intent || '—' }}</td>
            <td :class="row.rule_pass ? 'admin-pass' : 'admin-fail'">{{ row.rule_pass ? '通过' : '未过' }}</td>
            <td :class="row.judge?.intent_ok ? 'admin-pass' : 'admin-fail'">
              {{ row.judge ? (row.judge.intent_ok ? '通过' : '未过') : '—' }}
            </td>
            <td :class="row.judge?.safety_ok ? 'admin-pass' : 'admin-fail'">
              {{ row.judge ? (row.judge.safety_ok ? '通过' : '未过') : '—' }}
            </td>
            <td class="num">{{ row.judge ? row.judge.quality : '—' }}</td>
            <td class="wrap">{{ row.judge?.reason || row.rule_reason || '—' }}</td>
          </tr>
          <tr v-if="!caseRows.length">
            <td colspan="9" class="admin-empty">暂无用例明细</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div v-else class="admin-empty">暂不支持的报告类型</div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EvalKind } from '../../types'
import { cny, metric, ms, num, pct, seconds, shortSha } from './format'

const props = defineProps<{
  kind: EvalKind
  report: Record<string, any>
}>()

const showAllDetails = ref(false)

const MODE_LABELS: Record<string, string> = {
  dense: '稠密向量',
  sparse: 'BM25 稀疏',
  hybrid: '混合检索',
}
const TYPE_LABELS: Record<string, string> = {
  base: '基础集',
  hard_same_city: '同城不同景点',
  hard_cross_city: '跨城同名景点',
  long_doc: '长文档（多子块）',
  fuzzy: '模糊 query',
}
const CATEGORY_LABELS: Record<string, string> = {
  precise: '精准意图',
  fuzzy: '模糊意图',
  dangerous: '危险意图',
}

function modeLabel(mode: string): string {
  return MODE_LABELS[mode] ?? mode
}
function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type
}
function categoryLabel(name: string): string {
  return CATEGORY_LABELS[name] ?? name
}

/* ---------- 检索 ---------- */
const primary = computed(() => {
  const results = props.report.results || {}
  return results.hybrid || results.dense || Object.values(results)[0] || {}
})
const primaryMetrics = computed<Record<string, any>>(() => {
  const value = primary.value as Record<string, any>
  return value.metrics || {}
})
const usage = computed<Record<string, any>>(() => props.report.usage || {})

const ablationRows = computed<any[]>(() => {
  const rows = props.report.ablation || []
  if (rows.length) return rows as any[]
  return Object.entries(props.report.results || {}).map(([mode, data]: [string, any]) => ({
    mode,
    hyde: false,
    ...(data?.metrics || {}),
    usage: data?.usage || {},
  }))
})

const byTypeRows = computed<any[]>(() => {
  const value = primary.value as Record<string, any>
  const byType = value.by_type || {}
  return Object.entries(byType).map(([type, data]: [string, any]) => ({ type, ...data }))
})

const cityCheck = computed<Record<string, any> | null>(() => props.report.city_filter_check || null)

const detailRows = computed<any[]>(() => {
  const value = primary.value as Record<string, any>
  return (value.details || []) as any[]
})
const visibleDetails = computed(() => (showAllDetails.value ? detailRows.value : detailRows.value.slice(0, 30)))

/* ---------- 对话 ---------- */
const summary = computed<Record<string, any>>(() => props.report.summary || {})
const overall = computed<Record<string, any>>(() => summary.value.overall || {})
const byCategory = computed<Record<string, any>>(() => summary.value.by_category || {})
const actualIntents = computed<Record<string, number>>(() => summary.value.actual_intents || {})
const caseRows = computed<any[]>(() => (props.report.cases || []) as any[])
const visibleCases = computed(() => (showAllDetails.value ? caseRows.value : caseRows.value.slice(0, 30)))
</script>
