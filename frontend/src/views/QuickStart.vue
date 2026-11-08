<template>
  <div class="sketchbook">
    <div class="sketchbook-wash" aria-hidden="true"></div>

    <router-link to="/" class="back-home" aria-label="返回首页">← 返回首页</router-link>

    <header class="sb-head">
      <p class="sb-kicker">看看大家都去哪儿</p>
      <h1 class="sb-title">翻开一页 · 遇见一座城</h1>
      <p class="sb-sub">选一座城，写下你的旅行偏好，交给旅迹智绘为你书写每一天的行程。</p>
    </header>

    <SketchbookBook v-model:index="activeIndex" :pages="cities">
      <template #sheet>
        <SketchbookForm
          v-if="!generating"
          :city="form.city"
          v-model:dates="form.dates"
          v-model:travel-days="form.travel_days"
          v-model:transportation="form.transportation"
          v-model:accommodation="form.accommodation"
          v-model:preferences="form.preferences"
          v-model:free-text-input="form.free_text_input"
          @submit="onSubmit"
        />
      </template>
    </SketchbookBook>

    <SketchbookProgress
      v-if="generating"
      :percent="progress.percent"
      :current="progress.current"
      :steps="steps"
      :step-done="progress.stepDone"
      :active-step="activeStep"
      :logs="logs"
      @cancel="cancel"
    />
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs, { type Dayjs } from 'dayjs'
import SketchbookBook from '../components/sketchbook/SketchbookBook.vue'
import SketchbookForm from '../components/sketchbook/SketchbookForm.vue'
import SketchbookProgress from '../components/sketchbook/SketchbookProgress.vue'
import { sketchbookCities } from '../data/sketchbookCities'
import { streamTripPlan } from '../services/api'
import { getSessionId, tripStore } from '../store'
import { usePaperTheme } from '../composables/usePaperTheme'
import type { TripRequest, StreamEvent } from '../types'

usePaperTheme()

const router = useRouter()
const route = useRoute()
const cities = sketchbookCities
const activeIndex = ref(0)

const form = reactive<{
  city: string
  dates: [Dayjs, Dayjs] | null
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
}>({
  city: cities[0].name,
  dates: [dayjs().add(1, 'day'), dayjs().add(3, 'day')],
  travel_days: 3,
  transportation: '公共交通',
  accommodation: '舒适型酒店',
  preferences: ['自然风光', '美食'],
  free_text_input: '希望氛围浪漫轻松、慢节奏',
})

// 从对话页带过来的 session_id，优先于当前浏览器默认会话 ID
const prefillSessionId = ref<string | undefined>()

// 当前翻开哪页 = 目的地城市
watch(activeIndex, (i) => {
  form.city = cities[i].name
})

/* ------- 进度状态（由后端 SSE 流事件驱动） ------- */
const steps = [
  { icon: '🔍', label: '搜索景点', nodes: ['attraction_tool_node', 'attraction_enrich_node', 'rag_info_node'] },
  { icon: '🌤️', label: '查询天气', nodes: ['weather_tool_node'] },
  { icon: '🏨', label: '推荐酒店', nodes: ['hotel_tool_node', 'hotel_enrich_node'] },
  { icon: '📋', label: '生成计划', nodes: ['plan_node'] },
]

// 节点所属阶段（与 steps 顺序一致），用于保证进度只进不退
const nodeStep: Record<string, number> = {
  attraction_tool_node: 0,
  rag_info_node: 0,
  attraction_enrich_node: 0,
  weather_tool_node: 1,
  hotel_tool_node: 2,
  hotel_enrich_node: 2,
  plan_node: 3,
  evaluation_node: 3,
}

const nodeMilestones: { node: string; pct: number }[] = [
  { node: 'attraction_tool_node', pct: 10 },
  { node: 'rag_info_node', pct: 25 },
  { node: 'weather_tool_node', pct: 35 },
  { node: 'attraction_enrich_node', pct: 50 },
  { node: 'hotel_tool_node', pct: 65 },
  { node: 'hotel_enrich_node', pct: 78 },
  { node: 'plan_node', pct: 90 },
]

const nodeLabels: Record<string, string> = {
  attraction_tool_node: '正在搜索景点…',
  attraction_enrich_node: '正在整合景点数据…',
  rag_info_node: '正在检索本地知识库…',
  weather_tool_node: '正在查询天气…',
  hotel_tool_node: '正在搜索推荐酒店…',
  hotel_enrich_node: '正在整合酒店数据…',
  plan_node: '正在生成行程计划…',
}

const generating = ref(false)
const cancelled = ref(false)
const progress = reactive<{ percent: number; current: string; currentNode: string; stepDone: boolean[] }>({
  percent: 0,
  current: '',
  currentNode: '',
  stepDone: [false, false, false, false],
})
const logs = ref<{ level: 'info' | 'warn' | 'success'; text: string }[]>([])
const nodeDone = new Set<string>()
// 已到达的最高阶段：并行分支或 RAG 回搜可能带来更早阶段的事件，届时直接忽略
let reachedStep = -1
let abortCtrl: AbortController | null = null
let redirectTimer: number | undefined

const activeStep = computed(() => {
  const node = progress.currentNode
  if (!node) return -1
  return nodeStep[node] ?? -1
})

function pushLog(level: 'info' | 'warn' | 'success', text: string) {
  logs.value.push({ level, text })
  if (logs.value.length > 60) logs.value.shift()
}

function onStreamEvent(ev: StreamEvent) {
  switch (ev.type) {
    case 'node_start': {
      const step = nodeStep[ev.node] ?? -1
      // 已进入更靠后的阶段时，忽略前面阶段的事件，避免进度回退
      if (step >= 0 && step < reachedStep) break
      if (step > reachedStep) reachedStep = step
      progress.currentNode = ev.node
      progress.current = ev.label || nodeLabels[ev.node] || ev.node
      pushLog('info', progress.current)
      break
    }
    case 'node_end': {
      nodeDone.add(ev.node)
      steps.forEach((s, i) => {
        if (s.nodes.includes(ev.node) && s.nodes.every((n) => nodeDone.has(n))) {
          progress.stepDone[i] = true
        }
      })
      for (const m of nodeMilestones) {
        if (m.node === ev.node) progress.percent = Math.max(progress.percent, m.pct)
      }
      break
    }
    case 'node_error':
      pushLog('warn', `${nodeLabels[ev.node] || ev.node} 出错，正在重试…`)
      break
    case 'done':
      break
  }
}

async function onSubmit() {
  if (!form.city || !form.dates) return

  const req: TripRequest = {
    city: form.city,
    start_date: form.dates[0].format('YYYY-MM-DD'),
    end_date: form.dates[1].format('YYYY-MM-DD'),
    travel_days: form.travel_days,
    transportation: form.transportation,
    accommodation: form.accommodation,
    preferences: form.preferences,
    free_text_input: form.free_text_input,
    session_id: prefillSessionId.value || getSessionId(),
  }

  generating.value = true
  cancelled.value = false
  progress.percent = 0
  progress.current = ''
  progress.currentNode = ''
  progress.stepDone = [false, false, false, false]
  nodeDone.clear()
  reachedStep = -1
  logs.value = []
  abortCtrl = new AbortController()

  try {
    for await (const ev of streamTripPlan(req, abortCtrl.signal)) {
      if (cancelled.value) return
      onStreamEvent(ev)
      if (ev.type === 'done') {
        if (!ev.success) {
          message.error(ev.message || '规划失败，请稍后重试')
          reset()
          return
        }
        progress.percent = 100
        tripStore.plan = ev.data ?? null
        pushLog('success', '行程规划完成！')
        message.success('行程规划完成！')
        redirectTimer = window.setTimeout(() => router.push('/result'), 600)
        return
      }
    }
  } catch (e: any) {
    if (e?.name !== 'AbortError' && !cancelled.value) {
      message.error('请求失败：' + (e?.message || '网络异常，请重试'))
    }
    reset()
  }
}

function cancel() {
  cancelled.value = true
  abortCtrl?.abort()
  reset()
}

function reset() {
  generating.value = false
  progress.current = ''
  progress.currentNode = ''
}

/* ------- 跨入口预填（对话页 / 首页城市链接），优先级 prefill > ?city= ------- */
onMounted(() => {
  let appliedPrefill = false
  const p = tripStore.prefill
  if (p) {
    appliedPrefill = true
    prefillSessionId.value = p.session_id
    if (p.city) {
      const i = cities.findIndex((c) => c.name === p.city || c.slug === p.city)
      if (i >= 0) {
        activeIndex.value = i
        form.city = cities[i].name
      }
    }
    if (p.start_date && p.end_date) {
      const s = dayjs(p.start_date)
      const e = dayjs(p.end_date)
      if (s.isValid() && e.isValid()) form.dates = [s, e]
    }
    if (p.travel_days) form.travel_days = p.travel_days
    if (p.transportation) form.transportation = p.transportation
    if (p.accommodation) form.accommodation = p.accommodation
    if (p.preferences?.length) form.preferences = [...p.preferences]
    if (typeof p.free_text_input === 'string') form.free_text_input = p.free_text_input
    tripStore.prefill = null
  }

  const qCity = typeof route.query.city === 'string' ? route.query.city : ''
  if (qCity) {
    if (!appliedPrefill) {
      const i = cities.findIndex((c) => c.name === qCity || c.slug === qCity)
      if (i >= 0) {
        activeIndex.value = i
        form.city = cities[i].name
      }
    }
    router.replace({ path: '/quick-start' })
  }
})

onUnmounted(() => {
  abortCtrl?.abort()
  if (redirectTimer) window.clearTimeout(redirectTimer)
})
</script>

<style scoped>
.sketchbook {
  padding-bottom: 56px;
}
.back-home {
  position: fixed;
  top: 18px;
  left: 18px;
  z-index: 120;
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 0 13px;
  border: 1px solid var(--hairline);
  border-radius: 999px;
  background: rgba(236, 231, 220, 0.82);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  font-size: 12px;
  letter-spacing: 0.04em;
  color: var(--ink-soft);
  text-decoration: none;
  transition: color 0.2s, border-color 0.2s;
}
.back-home:hover {
  color: var(--ink);
  border-color: var(--ink);
}
.sb-head {
  text-align: center;
  padding: 44px 20px 10px;
}
.sb-kicker {
  margin: 0 0 12px;
  font-size: 12px;
  letter-spacing: var(--track-caps);
  text-transform: uppercase;
  color: var(--ink-soft);
}
.sb-title {
  margin: 0;
  font-family: var(--display);
  font-size: clamp(28px, 4vw, 44px);
  font-weight: 400;
  letter-spacing: 0.01em;
  color: var(--ink);
}
.sb-sub {
  margin: 12px auto 0;
  font-size: 14px;
  color: var(--ink-soft);
  line-height: 1.7;
  max-width: 560px;
}

@media (max-width: 560px) {
  .back-home {
    top: 12px;
    left: 12px;
    height: 28px;
    padding: 0 10px;
    font-size: 11px;
  }
}
</style>
