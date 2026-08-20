<template>
  <div class="home">
    <!-- 背景装饰 -->
    <div class="blob blob-1"></div>
    <div class="blob blob-2"></div>
    <div class="blob blob-3"></div>
    <div class="stars" aria-hidden="true"></div>

    <div class="home-inner">
      <!-- 左侧：品牌 + 高德地图 -->
      <section class="left">
        <header class="brand fade-up">
          <div class="brand-badge">
            <span class="dot"></span>
            AI 驱动的行程规划引擎
          </div>
          <h1 class="brand-title">
            让 AI 为你规划<br />
            <span class="grad-text">一段心动旅程</span>
          </h1>
          <p class="brand-sub">
            点击地图上的城市，或直接填写右侧信息，交给 LangGraph 多智能体为你定制每一天的完美行程。
          </p>
        </header>

        <div class="map-stage fade-up" style="animation-delay: 0.08s">
          <div ref="mapEl" class="map-container"></div>
          <div v-if="mapNotice" class="map-notice">{{ mapNotice }}</div>
          <div class="map-hint">🖱️ 拖拽平移 · 滚轮 / 按钮缩放 · 点击城市选择目的地</div>
        </div>
      </section>

      <!-- 右侧：信息填写表单 -->
      <section class="right">
        <div ref="panelEl" class="panel glass-card fade-up" style="animation-delay: 0.14s">
          <!-- 表单模式 -->
          <template v-if="!generating">
            <div class="panel-head">
              <h2>开始规划</h2>
              <p>填写旅行偏好，剩下交给我们</p>
            </div>

            <div v-if="form.city" class="city-picked">
              <span>📍</span> 已选目的地：<b>{{ form.city }}</b>
            </div>

            <a-form layout="vertical" :model="form" @finish="onSubmit" class="form">
              <a-form-item label="目的地城市" name="city" :rules="[{ required: true, message: '请输入目的地城市' }]">
                <a-auto-complete
                  v-model:value="form.city"
                  :options="cityOptions"
                  placeholder="例如：青岛、成都、大理…"
                  style="width: 100%"
                  @select="onAutoSelect"
                >
                  <template #option="{ value }">
                    <span class="city-opt">📍 {{ value }}</span>
                  </template>
                </a-auto-complete>
                <div class="chips">
                  <a-tag
                    v-for="c in hotCities"
                    :key="c"
                    class="chip"
                    :class="{ active: form.city === c }"
                    @click="selectCity(c)"
                  >
                    {{ c }}
                  </a-tag>
                </div>
              </a-form-item>

              <div class="row-2">
                <a-form-item label="旅行日期" name="dates" style="flex: 1">
                  <a-range-picker
                    v-model:value="form.dates"
                    format="YYYY-MM-DD"
                    style="width: 100%"
                    :allow-clear="false"
                  />
                </a-form-item>
                <a-form-item label="旅行天数" name="travel_days" style="width: 118px">
                  <a-input-number v-model:value="form.travel_days" :min="1" :max="30" style="width: 100%" />
                </a-form-item>
              </div>

              <div class="row-2 row-equal">
                <a-form-item label="交通方式" name="transportation">
                  <a-auto-complete
                    v-model:value="form.transportation"
                    :options="transportationOptions"
                    placeholder="下拉选择或自定义"
                    style="width: 100%"
                  />
                </a-form-item>
                <a-form-item label="住宿偏好" name="accommodation">
                  <a-auto-complete
                    v-model:value="form.accommodation"
                    :options="accommodationOptions"
                    placeholder="下拉选择或自定义"
                    style="width: 100%"
                  />
                </a-form-item>
              </div>

              <a-form-item label="旅行偏好（可多选，也可输入自定义）" name="preferences">
                <a-select
                  v-model:value="form.preferences"
                  mode="tags"
                  placeholder="选择或输入，如：自然风光、美食…"
                  :max-tag-count="4"
                >
                  <a-select-option v-for="p in preferenceOptions" :key="p" :value="p">{{ p }}</a-select-option>
                </a-select>
              </a-form-item>

              <a-form-item label="额外要求" name="free_text_input">
                <a-textarea
                  v-model:value="form.free_text_input"
                  :rows="2"
                  placeholder="例如：希望氛围浪漫轻松、节奏慢一些，多安排博物馆…"
                />
              </a-form-item>

              <a-button type="primary" html-type="submit" size="large" block class="submit-btn">
                <template #icon><span>✨</span></template>
                生成我的旅行计划
              </a-button>
            </a-form>
          </template>

          <!-- 生成进度模式 -->
          <template v-else>
            <div class="progress-view">
              <div class="progress-icon breathe">🧭</div>
              <h2 class="progress-title">正在为你规划旅行…</h2>

              <div class="status-line" v-if="progress.current">
                <a-spin :spinning="true" :size="'small'" />
                <span>{{ progress.current }}</span>
              </div>

              <div class="steps">
                <div
                  v-for="(s, i) in steps"
                  :key="s.label"
                  class="step"
                  :class="{
                    done: progress.stepDone[i],
                    active: !progress.stepDone[i] && isNodeInStep(progress.currentNode, i),
                  }"
                >
                  <div class="step-ic">
                    <a-spin
                      v-if="!progress.stepDone[i] && isNodeInStep(progress.currentNode, i)"
                      :spinning="true"
                      :size="'small'"
                    />
                    <span v-else-if="progress.stepDone[i]">✅</span>
                    <span v-else>{{ s.icon }}</span>
                  </div>
                  <span class="step-label">{{ s.label }}</span>
                </div>
              </div>

              <a-progress
                :percent="progress.percent"
                :stroke-color="['#ffb703', '#ff6b6b', '#c75b9c']"
                :show-info="false"
                class="progress-bar"
              />

              <div class="progress-log" v-if="logs.length">
                <div v-for="(l, i) in logs" :key="i" class="log-line" :class="l.level">
                  <span class="log-dot"></span>{{ l.text }}
                </div>
              </div>

              <div class="progress-actions">
                <a-button type="text" danger @click="cancel" :disabled="!allowCancel">
                  取消生成
                </a-button>
              </div>
            </div>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs, { type Dayjs } from 'dayjs'
import AMapLoader from '@amap/amap-jsapi-loader'
import { chinaCities, cityCoord } from '../data/cities'
import { streamTripPlan } from '../services/api'
import { tripStore } from '../store'
import type { TripRequest, StreamEvent } from '../types'

const router = useRouter()

const hotCities = ['北京', '上海', '成都', '杭州', '西安', '青岛', '厦门', '大理']
const cityOptions = chinaCities.map((c) => ({ value: c.name }))
const transportationOptions = ['公共交通', '自驾', '包车', '骑行', '高铁', '飞机'].map((v) => ({ value: v }))
const accommodationOptions = ['经济型酒店', '舒适型酒店', '豪华酒店', '民宿', '青年旅舍'].map((v) => ({ value: v }))
const preferenceOptions = ['历史文化', '自然风光', '美食', '休闲度假', '亲子', '购物', '夜生活', '博物馆', '海滩', '主题公园', '摄影', '户外徒步', '古镇', '温泉']

const form = reactive<{
  city: string
  dates: [Dayjs, Dayjs] | null
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
}>({
  city: '青岛',
  dates: [dayjs().add(1, 'day'), dayjs().add(3, 'day')],
  travel_days: 3,
  transportation: '公共交通',
  accommodation: '舒适型酒店',
  preferences: ['自然风光', '美食'],
  free_text_input: '希望氛围浪漫轻松、慢节奏',
})

const panelEl = ref<HTMLElement>()

// ------- 高德地图 -------
const mapEl = ref<HTMLDivElement>()
const mapNotice = ref('')
let map: any = null
let AMapCtor: any = null
let cityMarkers: any[] = []
let highlightMarker: any = null

/** 主要城市（全国视图时优先展示，避免东部 300+ 城市重叠成一片） */
const majorCitySet = new Set(
  [
    '北京', '上海', '天津', '重庆',
    '广州', '深圳', '成都', '杭州', '西安', '南京', '武汉', '长沙', '郑州', '济南', '青岛',
    '沈阳', '大连', '哈尔滨', '长春', '石家庄', '太原', '呼和浩特', '兰州', '西宁', '银川',
    '乌鲁木齐', '拉萨', '贵阳', '昆明', '南宁', '海口', '三亚', '福州', '厦门', '南昌', '合肥',
    '苏州', '无锡', '桂林', '大理', '丽江', '张家界', '洛阳', '开封', '秦皇岛', '黄山',
    '珠海', '宁波', '温州', '威海', '烟台', '敦煌',
  ].filter((n) => chinaCities.some((c) => c.name === n))
)

/** 根据缩放级别显示城市点：全国视图只显示主要城市，放大后显示全部 */
function refreshVisibleMarkers() {
  if (!map || !cityMarkers.length) return
  const z = map.getZoom()
  const showAll = z >= 5.5
  cityMarkers.forEach((m) => {
    const isMajor = majorCitySet.has(m.getExtData().name)
    if (showAll || isMajor) m.show()
    else m.hide()
  })
}

/** 选择目的地：更新表单 + 地图高亮；非地图点击时顺便把视野平移过去 */
function selectCity(name: string, fromMap = false) {
  form.city = name
  updateHighlight(name)
  message.success(`已选择目的地：${name}`)
  if (!fromMap && map && cityCoord[name]) {
    map.panTo(cityCoord[name])
  }
}

/** 地图城市点点击 → 选择（不平移，用户正看着它） */
function onMapCitySelect(name: string) {
  selectCity(name, true)
}

/** 下拉选中目的地 */
function onAutoSelect(value: string | number) {
  selectCity(String(value))
}

/** 高亮当前选中的城市点（金色 + 标签） */
function updateHighlight(name: string) {
  if (!map || !AMapCtor) return
  if (highlightMarker) {
    map.remove(highlightMarker)
    highlightMarker = null
  }
  const coord = cityCoord[name]
  if (!coord) return
  highlightMarker = new AMapCtor.Marker({
    position: [coord[0], coord[1]],
    content: `<div class="home-city-highlight"><span>${name}</span></div>`,
    offset: new AMapCtor.Pixel(-22, -22),
    zIndex: 120,
  })
  map.add(highlightMarker)
}

async function initMap() {
  const key = import.meta.env.VITE_AMAP_WEB_JS_KEY
  if (!key) {
    mapNotice.value = '未配置 VITE_AMAP_WEB_JS_KEY，地图无法加载（请填入高德 Web 端 JS Key）'
    return
  }
  if (!mapEl.value) return

  try {
    const securityCode = (import.meta.env as any).VITE_AMAP_SECURITY_CODE
    if (securityCode) {
      ;(window as any)._AMapSecurityConfig = { securityJsCode: securityCode }
    }

    const AMap: any = await AMapLoader.load({
      key,
      version: '2.0',
      plugins: ['AMap.Scale', 'AMap.ToolBar'],
    })

    AMapCtor = AMap
    map = new AMap.Map(mapEl.value, {
      zoom: 5,
      center: [104.5, 35.5],
      viewMode: '2D',
      mapStyle: 'amap://styles/darkblue',
    })
    // 缩放时按级别切换城市点显示
    map.on('zoomend', refreshVisibleMarkers)
    // 默认展示中国全貌：按所有城市坐标的包围盒 fit
    setChinaView()
    renderCityMarkers()
    // 若初始已选城市，补一个高亮点
    updateHighlight(form.city)
    // DEV 调试钩子
    if (import.meta.env.DEV) {
      ;(window as any).__homeMap = { map, markerCount: chinaCities.length }
    }
  } catch (e: any) {
    console.error('地图加载失败', e)
    mapNotice.value = '地图加载失败：' + (e?.message || '请检查 Web JS Key 配置')
  }
}

/** 将视野 fit 到中国全貌（城市点包围盒 + 边距） */
function setChinaView() {
  if (!map || !AMapCtor || !chinaCities.length) return
  const lngs = chinaCities.map((c) => c.lng)
  const lats = chinaCities.map((c) => c.lat)
  const b = new AMapCtor.Bounds(
    [Math.min(...lngs) - 3, Math.min(...lats) - 3],
    [Math.max(...lngs) + 3, Math.max(...lats) + 3]
  )
  map.setBounds(b)
}

/** 渲染全国城市点：普通 marker，按缩放级别控制显隐，避免东部密集重叠 */
function renderCityMarkers() {
  if (!map || !AMapCtor) return
  const AMap = AMapCtor
  cityMarkers = chinaCities.map((c) => {
    const m = new AMap.Marker({
      position: [c.lng, c.lat],
      content: '<div class="home-city-dot"></div>',
      offset: new AMap.Pixel(-6, -6),
      zIndex: 80,
      extData: { name: c.name },
    })
    m.on('click', () => onMapCitySelect(c.name))
    return m
  })
  map.add(cityMarkers)
  refreshVisibleMarkers()
}

watch(
  () => form.city,
  (name) => updateHighlight(name)
)

onMounted(() => {
  initMap()
})

onUnmounted(() => {
  if (map) map.destroy()
  map = null
  cityMarkers = []
})

// ------- 进度状态（由后端 SSE 流事件驱动） -------
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
  attraction_tool_node: '正在搜索景点...',
  attraction_enrich_node: '正在整合景点数据...',
  rag_info_node: '正在检索本地知识库...',
  weather_tool_node: '正在查询天气...',
  hotel_tool_node: '正在搜索推荐酒店...',
  hotel_enrich_node: '正在整合酒店数据...',
  plan_node: '正在生成行程计划...',
}

const generating = ref(false)
const allowCancel = ref(false)
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

function isNodeInStep(node: string, stepIndex: number): boolean {
  return !!node && steps[stepIndex].nodes.includes(node)
}

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
  allowCancel.value = true
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
          message.error(ev.message || '生成失败，请稍后重试')
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
  allowCancel.value = false
  cancelled.value = true
  abortCtrl?.abort()
  reset()
}

function reset() {
  generating.value = false
  allowCancel.value = false
  progress.current = ''
  progress.currentNode = ''
}

onUnmounted(() => {
  abortCtrl?.abort()
})
</script>

<style scoped>
.home {
  position: relative;
  height: 100vh;
  min-height: 720px;
  overflow: hidden;
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(199, 91, 156, 0.35), transparent 60%),
    radial-gradient(900px 500px at -10% 30%, rgba(74, 45, 107, 0.5), transparent 55%),
    linear-gradient(135deg, #0b1026 0%, #151a3d 40%, #221c4d 70%, #3b2458 100%);
  color: #fff;
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.4;
  animation: float 9s ease-in-out infinite;
  pointer-events: none;
}
.blob-1 { width: 380px; height: 380px; background: #c75b9c; top: -80px; right: 4%; }
.blob-2 { width: 320px; height: 320px; background: #f29a4e; bottom: -100px; left: 4%; animation-delay: -3s; }
.blob-3 { width: 240px; height: 240px; background: #43c6ac; top: 38%; left: 46%; opacity: 0.2; animation-delay: -6s; }
@keyframes float {
  0%, 100% { transform: translateY(0) translateX(0); }
  50% { transform: translateY(-30px) translateX(20px); }
}

.stars {
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(2px 2px at 20% 30%, rgba(255,255,255,0.6), transparent),
    radial-gradient(2px 2px at 70% 20%, rgba(255,255,255,0.45), transparent),
    radial-gradient(1.5px 1.5px at 40% 70%, rgba(255,255,255,0.5), transparent),
    radial-gradient(1.5px 1.5px at 85% 60%, rgba(255,255,255,0.35), transparent);
  pointer-events: none;
}

.home-inner {
  position: relative;
  z-index: 1;
  height: 100%;
  max-width: 1680px;
  margin: 0 auto;
  padding: 24px 32px;
  display: flex;
  gap: 26px;
}

/* ---- 左侧：品牌 + 地图 ---- */
.left {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.brand-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.22);
  background: rgba(255, 255, 255, 0.07);
  font-size: 13px;
  letter-spacing: 0.5px;
}
.brand-badge .dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #43f0c5;
  box-shadow: 0 0 10px #43f0c5;
}
.brand-title {
  margin-top: 14px;
  font-size: 40px;
  line-height: 1.2;
  font-weight: 800;
  letter-spacing: 1px;
}
.brand-sub {
  margin-top: 10px;
  color: rgba(255, 255, 255, 0.72);
  line-height: 1.7;
  font-size: 14px;
  max-width: 520px;
}

.map-stage {
  flex: 1;
  min-height: 380px;
  margin-top: 14px;
  position: relative;
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.16);
  box-shadow: 0 24px 60px -24px rgba(0, 0, 0, 0.7);
}
.map-container {
  width: 100%;
  height: 100%;
}
.map-notice {
  position: absolute;
  left: 12px;
  top: 12px;
  z-index: 5;
  padding: 8px 14px;
  border-radius: 10px;
  background: rgba(11, 16, 38, 0.85);
  border: 1px solid rgba(255, 107, 107, 0.5);
  font-size: 13px;
  color: #ff9a9a;
}
.map-hint {
  position: absolute;
  left: 50%;
  bottom: 14px;
  transform: translateX(-50%);
  z-index: 5;
  padding: 7px 16px;
  border-radius: 999px;
  background: rgba(11, 16, 38, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.18);
  font-size: 12px;
  color: rgba(255, 255, 255, 0.85);
  white-space: nowrap;
}

/* ---- 右侧：表单卡 ---- */
.right {
  width: 440px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
}
.panel {
  width: 100%;
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  padding: 26px 26px 28px;
  color: #fff;
}
.panel::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.25); }
.panel-head h2 { font-size: 24px; font-weight: 700; }
.panel-head p { color: rgba(255, 255, 255, 0.65); font-size: 13px; margin-top: 4px; }
.panel-head { margin-bottom: 16px; }

.city-picked {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 14px;
  padding: 9px 12px;
  border-radius: 10px;
  background: rgba(255, 209, 102, 0.12);
  border: 1px solid rgba(255, 209, 102, 0.3);
  font-size: 13px;
}
.city-picked b { color: var(--gold); margin-left: 2px; }

.form :deep(.ant-form-item-label > label) {
  color: rgba(255, 255, 255, 0.85);
  font-weight: 500;
}
.form :deep(.ant-input),
.form :deep(.ant-select-selector),
.form :deep(.ant-picker),
.form :deep(.ant-input-number),
.form :deep(.ant-input-affix-wrapper) {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.22);
  color: #fff;
  border-radius: 10px;
}
.form :deep(.ant-input::placeholder) { color: rgba(255, 255, 255, 0.4); }
.form :deep(.ant-picker-input > input) { color: #fff; }
.form :deep(.ant-select-selection-placeholder) { color: rgba(255, 255, 255, 0.4); }
.form :deep(.ant-select-selection-item) { color: #fff; }
.form :deep(.ant-select-tag) {
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
  color: #fff;
}
.form :deep(.ant-picker-suffix) { color: rgba(255, 255, 255, 0.5); }

.row-2 { display: flex; gap: 12px; }
/* 均分两列：用 grid 强制 1fr 1fr，避免 antd form-item 内联 flex 不生效导致缩成内容宽度 */
.row-equal {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.row-equal :deep(.ant-form-item) {
  min-width: 0;
}

.chips { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  cursor: pointer;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid transparent;
  color: rgba(255, 255, 255, 0.75);
  transition: all 0.2s;
  margin-inline-end: 0;
  user-select: none;
}
.chip:hover { border-color: rgba(255, 255, 255, 0.5); }
.chip.active {
  background: linear-gradient(120deg, #ffb703, #ff6b6b);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
}

.submit-btn {
  margin-top: 6px;
  height: 48px;
  font-size: 16px;
  border-radius: 12px;
  font-weight: 600;
  letter-spacing: 1px;
}

/* 进度视图 */
.progress-view { text-align: center; padding: 18px 8px; }
.progress-icon { font-size: 52px; display: inline-block; }
.progress-title { margin-top: 14px; font-size: 22px; }
.steps { margin: 26px 0 18px; display: flex; justify-content: space-between; gap: 8px; }
.step { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 8px; opacity: 0.45; transition: all 0.3s; }
.step.active { opacity: 1; }
.step.done { opacity: 0.85; }
.step-ic {
  width: 46px; height: 46px;
  display: grid; place-items: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.2);
  font-size: 20px;
}
.step.done .step-ic { border-color: transparent; }
.step.active .step-ic { border-color: var(--gold); box-shadow: 0 0 16px rgba(255, 183, 3, 0.6); }
.step-label { font-size: 12px; color: rgba(255, 255, 255, 0.8); white-space: nowrap; }
.progress-bar { margin: 6px 0 10px; }
.progress-actions { margin-top: 8px; }
.status-line {
  margin-top: 10px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.15);
  font-size: 13px;
  color: rgba(255, 255, 255, 0.9);
}
.progress-log {
  margin: 10px 0 6px;
  max-height: 120px;
  overflow-y: auto;
  text-align: left;
  background: rgba(0, 0, 0, 0.18);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 12px;
}
.log-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
  color: rgba(255, 255, 255, 0.65);
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.log-line.warn { color: #ffb703; }
.log-line.success { color: #43f0c5; }
.log-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(255, 255, 255, 0.35); flex-shrink: 0; }
.log-line.warn .log-dot { background: #ffb703; }
.log-line.success .log-dot { background: #43f0c5; }
.progress-actions :deep(.ant-btn) { color: rgba(255, 255, 255, 0.6); }

@media (max-width: 1180px) {
  .home { height: auto; min-height: 100vh; overflow: visible; }
  .home-inner { flex-direction: column; padding: 24px 20px; gap: 18px; }
  .map-stage { height: 480px; flex: none; }
  .right { width: 100%; }
  .panel { max-height: none; }
  .brand { text-align: center; }
  .brand-sub { margin: 10px auto 0; }
}
@media (max-width: 560px) {
  .brand-title { font-size: 32px; }
  .row-2 { flex-direction: column; }
  .panel { padding: 22px 18px; }
}
</style>

<style>
/* 地图 Marker / 聚合点样式（非 scoped，作用于 AMap 动态 DOM） */
.home-city-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #7dd8ff;
  border: 1.5px solid rgba(255, 255, 255, 0.75);
  box-shadow: 0 0 8px rgba(125, 216, 255, 0.9);
  cursor: pointer;
  transition: transform 0.15s;
}
.home-city-dot:hover { transform: scale(1.5); }

.home-city-highlight {
  position: relative;
  width: 26px;
  height: 26px;
  border-radius: 50% 50% 50% 0;
  transform: rotate(-45deg);
  background: linear-gradient(135deg, #ffd166, #ffb703);
  box-shadow: 0 0 18px rgba(255, 209, 102, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
}
.home-city-highlight span {
  transform: rotate(45deg);
  position: absolute;
  top: -22px;
  left: 50%;
  translate: -50% 0;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  background: rgba(11, 16, 38, 0.82);
  border: 1px solid rgba(255, 209, 102, 0.5);
  border-radius: 6px;
  padding: 2px 8px;
  white-space: nowrap;
}
</style>
