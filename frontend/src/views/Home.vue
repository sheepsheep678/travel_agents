<template>
  <div class="sketchbook">
    <div class="sketchbook-wash" aria-hidden="true"></div>

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
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs, { type Dayjs } from 'dayjs'
import SketchbookBook from '../components/sketchbook/SketchbookBook.vue'
import SketchbookForm from '../components/sketchbook/SketchbookForm.vue'
import SketchbookProgress from '../components/sketchbook/SketchbookProgress.vue'
import { sketchbookCities } from '../data/sketchbookCities'
import { streamTripPlan } from '../services/api'
import { tripStore } from '../store'
import type { TripRequest, StreamEvent } from '../types'

const router = useRouter()
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
let abortCtrl: AbortController | null = null

const activeStep = computed(() => {
  const node = progress.currentNode
  if (!node) return -1
  for (let i = 0; i < steps.length; i++) {
    if (steps[i].nodes.includes(node)) return i
  }
  return -1
})

function pushLog(level: 'info' | 'warn' | 'success', text: string) {
  logs.value.push({ level, text })
  if (logs.value.length > 60) logs.value.shift()
}

function onStreamEvent(ev: StreamEvent) {
  switch (ev.type) {
    case 'node_start':
      progress.currentNode = ev.node
      progress.current = ev.label || nodeLabels[ev.node] || ev.node
      pushLog('info', progress.current)
      break
    case 'node_end': {
      nodeDone.add(ev.node)
      steps.forEach((s, i) => {
        if (s.nodes.includes(ev.node) && s.nodes.every((n) => nodeDone.has(n))) {
          progress.stepDone[i] = true
        }
      })
      for (const m of nodeMilestones) {
        if (m.node === ev.node) progress.percent = m.pct
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
  }

  generating.value = true
  cancelled.value = false
  progress.percent = 0
  progress.current = ''
  progress.currentNode = ''
  progress.stepDone = [false, false, false, false]
  nodeDone.clear()
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
        window.setTimeout(() => router.push('/result'), 600)
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

onMounted(() => {
  document.body.classList.add('sketchbook-mode')
})

onUnmounted(() => {
  document.body.classList.remove('sketchbook-mode')
  abortCtrl?.abort()
})
</script>

<style scoped>
.sketchbook {
  padding-bottom: 56px;
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
</style>
