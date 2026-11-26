<template>
  <section class="admin-section">
    <header class="admin-section-head">
      <div>
        <h2>历史报告</h2>
        <p>results 目录下的评测报告；点击文件名查看完整明细。</p>
      </div>
      <div class="admin-section-actions">
        <button class="admin-btn admin-btn-ghost" :disabled="loading || !token" @click="load">
          {{ loading ? '读取中…' : '刷新列表' }}
        </button>
      </div>
    </header>

    <div v-if="!token" class="admin-alert info">请先在上方输入并保存管理端令牌（X-Admin-Token）。</div>
    <div v-if="error" class="admin-alert">{{ error }}</div>

    <div class="admin-table-wrap">
      <table class="admin-table">
        <thead>
          <tr>
            <th>报告</th>
            <th>类型</th>
            <th>生成时间</th>
            <th>范围</th>
            <th>耗时</th>
            <th>大小</th>
            <th>头部指标</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.name">
            <td>
              <button class="admin-report-name" @click="$emit('open', item.name)">{{ item.name }}</button>
            </td>
            <td>{{ item.kind === 'retrieval' ? '检索' : '对话' }}</td>
            <td>{{ item.generated_at || '—' }}</td>
            <td>
              <template v-if="item.kind === 'retrieval'">
                {{ item.dataset || '—' }} · {{ item.queries ?? '—' }} query
              </template>
              <template v-else>{{ item.headline?.total ?? '—' }} 用例</template>
            </td>
            <td class="num">{{ seconds(item.duration_seconds) }}</td>
            <td class="num">{{ bytes(item.size_bytes) }}</td>
            <td class="wrap">
              <template v-if="item.kind === 'retrieval'">
                Recall@1 {{ pct(item.headline?.['recall@1']) }} ·
                nDCG {{ num(item.headline?.ndcg, 3) }} ·
                P95 {{ ms(item.headline?.latency?.p95) }}
              </template>
              <template v-else>
                规则 {{ pct(item.headline?.rule_pass_rate) }} ·
                意图 {{ pct(item.headline?.intent_ok_rate) }} ·
                质量 {{ num(item.headline?.avg_quality, 1) }}
              </template>
            </td>
          </tr>
          <tr v-if="!items.length">
            <td colspan="7" class="admin-empty">暂无报告；先运行一次评测。</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { AdminReportItem } from '../../types'
import { adminErrorText, fetchAdminReports } from '../../services/admin'
import { bytes, ms, num, pct, seconds } from './format'

const props = defineProps<{ token: string }>()
defineEmits<{ (e: 'open', name: string): void }>()

const items = ref<AdminReportItem[]>([])
const loading = ref(false)
const error = ref('')

async function load(): Promise<void> {
  if (!props.token) return
  loading.value = true
  error.value = ''
  try {
    const data = await fetchAdminReports(props.token)
    items.value = data.items
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
