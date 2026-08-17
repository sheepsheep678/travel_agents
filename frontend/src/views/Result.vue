<template>
  <div class="result-page">
    <!-- 无数据占位 -->
    <div v-if="!plan" class="empty">
      <div class="empty-ic">🧳</div>
      <h2>还没有行程数据</h2>
      <p>先去填写你的旅行偏好，让 AI 为你生成一份专属计划吧</p>
      <a-button type="primary" size="large" @click="$router.push('/')">去规划 →</a-button>
    </div>

    <template v-else>
      <!-- 顶部固定摘要栏 -->
      <header class="topbar">
        <div class="topbar-inner">
          <div class="topbar-title">
            <div class="city-badge">{{ plan.city }}</div>
            <div class="topbar-meta">
              <span class="meta-date">{{ plan.start_date }} ~ {{ plan.end_date }}</span>
              <span class="meta-tag">共 {{ plan.days.length }} 天</span>
            </div>
          </div>
          <div class="topbar-total">
            <small>预计总花费</small>
            <b>¥ {{ plan.budget?.total ?? 0 }}</b>
          </div>
          <div class="topbar-actions">
            <a-button @click="exportPNG">
              <template #icon><PictureOutlined /></template>PNG
            </a-button>
            <a-button @click="exportPDF">
              <template #icon><FilePdfOutlined /></template>PDF
            </a-button>
            <a-button @click="$router.push('/')">重新规划</a-button>
          </div>
        </div>
      </header>

      <div class="result-body">
        <!-- 左侧锚点导航 -->
        <aside class="side-nav">
          <div class="side-nav-sticky">
            <div class="nav-title">目录</div>
            <a-menu mode="inline" :selected-keys="activeAnchor" class="nav-menu">
              <a-menu-item key="overview"><a href="#overview">📌 行程概览</a></a-menu-item>
              <a-menu-item key="budget"><a href="#budget">💰 预算明细</a></a-menu-item>
              <a-menu-item key="map"><a href="#map">🗺️ 路线地图</a></a-menu-item>
              <a-menu-item key="itinerary"><a href="#itinerary">🗓️ 每日行程</a></a-menu-item>
              <a-menu-item key="weather"><a href="#weather">🌤️ 天气信息</a></a-menu-item>
            </a-menu>
          </div>
        </aside>

        <!-- 右侧主体 -->
        <main ref="contentRef" class="content">
          <!-- 概览 -->
          <section id="overview" class="section card">
            <h2 class="sec-title">行程概览</h2>
            <p class="overview-text">{{ plan.overall_suggestions }}</p>
            <div class="quick-facts">
              <div class="fact"><span class="fact-ic">🏞️</span><b>{{ totalAttractions }}</b><small>个景点</small></div>
              <div class="fact"><span class="fact-ic">🏨</span><b>{{ totalHotels }}</b><small>家酒店</small></div>
              <div class="fact"><span class="fact-ic">🍽️</span><b>{{ totalMeals }}</b><small>次用餐</small></div>
              <div class="fact"><span class="fact-ic">🎫</span><b>¥{{ plan.budget?.total_attractions ?? 0 }}</b><small>门票预算</small></div>
            </div>
          </section>

          <!-- 预算 -->
          <section id="budget" class="section">
            <h2 class="sec-title">预算明细</h2>
            <div class="budget-grid">
              <div v-for="b in budgetItems" :key="b.key" class="budget-card" :style="{ background: b.bg }">
                <span class="budget-ic">{{ b.icon }}</span>
                <small>{{ b.label }}</small>
                <b>¥ {{ b.value }}</b>
              </div>
              <div class="budget-card total" :style="{ background: 'linear-gradient(120deg,#ffb703,#ff6b6b)' }">
                <span class="budget-ic">✨</span>
                <small>总预算</small>
                <b>¥ {{ plan.budget?.total ?? 0 }}</b>
              </div>
            </div>
          </section>

          <!-- 地图 -->
          <section id="map" class="section">
            <h2 class="sec-title">路线地图</h2>
            <a-alert
              v-if="mapNotice"
              :message="mapNotice"
              type="warning"
              show-icon
              class="map-notice"
            />
            <div ref="mapEl" class="map-container"></div>
            <div class="map-legend">
              <span v-for="(d, i) in days" :key="i" class="legend-item">
                <i :style="{ background: dayColor(i) }"></i> 第{{ i + 1 }}天
              </span>
              <span class="legend-item"><i class="legend-meal"></i> 餐饮</span>
              <span class="legend-item"><i class="legend-hotel"></i> 酒店</span>
            </div>
          </section>

          <!-- 每日行程 -->
          <section id="itinerary" class="section">
            <h2 class="sec-title">每日行程</h2>
            <div class="timeline">
              <div
                v-for="(day, di) in days"
                :key="di"
                class="tl-item"
                :class="{ left: di % 2 === 0, right: di % 2 === 1 }"
              >
                <div class="tl-dot" :style="{ background: dayColor(di) }">
                  <span>{{ di + 1 }}</span>
                </div>
                <div class="tl-card card">
                  <div class="day-head">
                    <div>
                      <span class="day-badge" :style="{ background: dayColor(di) }">第 {{ di + 1 }} 天</span>
                      <span class="day-date">{{ day.date }}</span>
                    </div>
                    <div class="day-desc">{{ day.description }}</div>
                  </div>

                  <!-- 景点列表（可编辑） -->
                  <div class="attr-list">
                    <div v-for="(a, ai) in day.attractions" :key="ai" class="attr-row">
                      <div class="attr-img-wrap">
                        <span class="attr-idx" :style="{ background: dayColor(di) }">{{ ai + 1 }}</span>
                        <span class="attr-img-ph">🏞️</span>
                        <img
                          v-if="attrImage(a)"
                          :src="attrImage(a)"
                          class="attr-img"
                          alt=""
                          loading="lazy"
                          @error="onImgError"
                        />
                      </div>
                      <div class="attr-main">
                        <div class="attr-name">
                          {{ a.name }}
                          <a-tag v-if="a.category" color="processing">{{ a.category }}</a-tag>
                        </div>
                        <div class="attr-meta">
                          <span>🕐 {{ a.visit_duration }} 分钟</span>
                          <span v-if="a.ticket_price">🎫 ¥{{ a.ticket_price }}</span>
                          <span v-else>🎫 免费</span>
                          <span v-if="a.rating">⭐ {{ a.rating }}</span>
                        </div>
                        <div class="attr-desc">{{ a.description }}</div>
                      </div>
                      <div class="attr-ops">
                        <a-button size="small" type="text" :disabled="ai === 0" @click="moveAttr(di, ai, -1)">
                          <ArrowUpOutlined />
                        </a-button>
                        <a-button size="small" type="text" :disabled="ai === day.attractions.length - 1" @click="moveAttr(di, ai, 1)">
                          <ArrowDownOutlined />
                        </a-button>
                        <a-button size="small" type="text" danger @click="removeAttr(di, ai)">
                          <DeleteOutlined />
                        </a-button>
                      </div>
                    </div>
                    <a-empty v-if="day.attractions.length === 0" description="当日暂无景点" :image="simpleEmpty" />
                  </div>

                  <!-- 餐饮 -->
                  <div class="meal-section">
                    <div class="meal-row" v-for="(m, mi) in day.meals" :key="mi">
                      <span class="meal-type" :class="'meal-' + m.type">{{ mealTypeLabel(m.type) }}</span>
                      <div class="meal-info">
                        <span class="meal-name">{{ m.name }}</span>
                        <span v-if="m.address || m.description" class="meal-sub">
                          {{ m.address }}{{ m.address && m.description ? ' · ' : '' }}{{ m.description }}
                        </span>
                      </div>
                      <span class="meal-cost" v-if="m.estimated_cost">约 ¥{{ m.estimated_cost }}</span>
                    </div>
                  </div>

                  <!-- 酒店 -->
                  <div class="hotel-card" v-if="day.hotel">
                    <div class="hotel-ic">🏨</div>
                    <div class="hotel-main">
                      <div class="hotel-title">
                        <b>{{ day.hotel.name }}</b>
                        <span v-if="day.hotel.type" class="hotel-type">{{ day.hotel.type }}</span>
                        <span v-if="day.hotel.rating" class="hotel-rating">⭐ {{ day.hotel.rating }}</span>
                      </div>
                      <span class="hotel-sub">{{ day.hotel.distance || day.hotel.address || '住宿推荐' }}</span>
                    </div>
                    <div class="hotel-side">
                      <span v-if="day.hotel.price_range" class="hotel-price-range">{{ day.hotel.price_range }}</span>
                      <span v-if="day.hotel.estimated_cost" class="hotel-cost">¥{{ day.hotel.estimated_cost }}/晚</span>
                    </div>
                  </div>

                  <div class="day-foot">
                    <span>🚇 交通：{{ day.transportation }}</span>
                    <span v-if="day.accommodation">🛏️ 住宿：{{ day.accommodation }}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 天气 -->
          <section id="weather" class="section">
            <h2 class="sec-title">天气信息</h2>
            <div class="weather-grid">
              <div v-for="w in plan.weather_info" :key="w.date" class="weather-card">
                <div class="w-date">{{ w.date }}</div>
                <div class="w-ic">{{ weatherIcon(w.day_weather) }}</div>
                <div class="w-weather">
                  <b>{{ w.day_weather || '暂无预报' }}</b>
                  <span v-if="w.day_temp">白天 {{ w.day_temp }}°C</span>
                  <span v-if="w.night_weather">夜间 {{ w.night_weather }} {{ w.night_temp }}°C</span>
                  <span v-if="w.wind_direction || w.wind_power">💨 {{ w.wind_direction }} {{ w.wind_power }}</span>
                </div>
              </div>
            </div>
          </section>

          <footer class="foot">✨ 由 LangGraph 多智能体生成 · AI 智能旅行助手</footer>
        </main>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { message, Empty } from 'ant-design-vue'
import {
  PictureOutlined,
  FilePdfOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'
import { tripStore } from '../store'
import type { TripPlan, DayPlan, Attraction } from '../types'

// ------- 数据 -------
const plan = computed<TripPlan | null>(() => tripStore.plan)
const days = reactive<DayPlan[]>([])
// 注意：plan 来自 reactive(tripStore)，其嵌套对象是 Proxy，不能用 structuredClone，
// 改用 JSON 深拷贝转成普通对象（计划数据本身是纯 JSON 结构）
if (plan.value) days.push(...(JSON.parse(JSON.stringify(plan.value.days)) as DayPlan[]))

const simpleEmpty = computed(() => Empty.PRESENTED_IMAGE_SIMPLE)

const DAY_COLORS = ['#ff6b6b', '#ffb703', '#43c6ac', '#7b61ff', '#2d9cdb', '#f29a4e', '#c75b9c', '#00b8d9']

function dayColor(i: number): string {
  return DAY_COLORS[i % DAY_COLORS.length]
}

const totalAttractions = computed(() => days.reduce((s, d) => s + d.attractions.length, 0))
const totalHotels = computed(() => days.filter((d) => d.hotel).length)
const totalMeals = computed(() => days.reduce((s, d) => s + d.meals.length, 0))

const budgetItems = computed(() => {
  const b = plan.value?.budget
  return [
    { key: 'attractions', label: '景点门票', value: b?.total_attractions ?? 0, icon: '🎫', bg: 'linear-gradient(135deg,#ff6b6b,#ff9a5a)' },
    { key: 'hotels', label: '酒店住宿', value: b?.total_hotels ?? 0, icon: '🏨', bg: 'linear-gradient(135deg,#7b61ff,#9b7bff)' },
    { key: 'meals', label: '餐饮', value: b?.total_meals ?? 0, icon: '🍜', bg: 'linear-gradient(135deg,#43c6ac,#5ee0c3)' },
    { key: 'transport', label: '交通', value: b?.total_transportation ?? 0, icon: '🚕', bg: 'linear-gradient(135deg,#2d9cdb,#5ab7e8)' },
  ]
})

function mealTypeLabel(t: string): string {
  return { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '小吃' }[t] || t
}

/** 取景点图片：优先封面图，其次图片列表第一张，都没有返回空串（走占位图）。高德图床为 http，统一升级为 https 防混合内容拦截 */
function attrImage(a: Attraction): string {
  const u = a.image_url || (Array.isArray(a.photos) && a.photos[0]) || ''
  return u ? u.replace(/^http:\/\//i, 'https://') : ''
}

/** 图片加载失败时隐藏 <img>，露出底下的占位图 */
function onImgError(e: Event) {
  const el = e.target as HTMLElement
  el.style.display = 'none'
}

function weatherIcon(w?: string): string {
  if (!w) return '🌤️'
  if (w.includes('雨')) return '🌧️'
  if (w.includes('雪')) return '🌨️'
  if (w.includes('阴')) return '☁️'
  if (w.includes('云')) return '⛅'
  if (w.includes('晴')) return '☀️'
  if (w.includes('雾')) return '🌫️'
  return '🌤️'
}

// ------- 编辑 -------
function moveAttr(di: number, ai: number, dir: -1 | 1) {
  const list = days[di].attractions
  const target = ai + dir
  if (target < 0 || target >= list.length) return
  ;[list[ai], list[target]] = [list[target], list[ai]]
  syncMap()
}

function removeAttr(di: number, ai: number) {
  days[di].attractions.splice(ai, 1)
  syncMap()
}

// ------- 地图 -------
const mapEl = ref<HTMLDivElement>()
const mapNotice = ref('')
let map: any = null
let AMapCtor: any = null
let infoWindow: any = null
let markers: any[] = []

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
      plugins: ['AMap.Scale', 'AMap.ToolBar', 'AMap.InfoWindow'],
    })

    AMapCtor = AMap
    map = new AMap.Map(mapEl.value, {
      zoom: 12,
      center: [116.397428, 39.90923],
      viewMode: '2D',
      mapStyle: 'amap://styles/whitesmoke',
    })
    infoWindow = new AMap.InfoWindow({ offset: new AMap.Pixel(0, -32) })
    renderMarkers()
  } catch (e: any) {
    console.error('地图加载失败', e)
    mapNotice.value = '地图加载失败：' + (e?.message || '请检查 Web JS Key 配置')
  }
}

function renderMarkers() {
  if (!map) return
  markers.forEach((m) => map.remove(m))
  markers = []

  let anyPoi = false
  days.forEach((day, di) => {
    const color = dayColor(di)

    // 酒店 marker（当日推荐住宿）
    const h = day.hotel
    if (h && h.location && typeof h.location.longitude === 'number') {
      anyPoi = true
      const marker = new AMapCtor.Marker({
        position: [h.location.longitude, h.location.latitude],
        title: h.name,
        zIndex: 101,
        content: `<div class="amap-hotel-marker" style="border-color:${color}">🏨</div>`,
        offset: new AMapCtor.Pixel(-16, -16),
      })
      marker.on('click', () => {
        infoWindow.setContent(
          `<div class="amap-infowindow">
             <b>🏨 ${h.name}</b>
             <p>${h.distance || h.address || '推荐住宿'}</p>
             <span>第 ${di + 1} 天</span>
           </div>`
        )
        infoWindow.open(map, marker.getPosition())
      })
      markers.push(marker)
      map.add(marker)
    }

    // 景点 marker（按天着色 + 编号）
    day.attractions.forEach((a: Attraction, ai) => {
      if (!a.location || typeof a.location.longitude !== 'number') return
      anyPoi = true
      const marker = new AMapCtor.Marker({
        position: [a.location.longitude, a.location.latitude],
        title: a.name,
        zIndex: 100,
        content: `<div class="amap-marker" style="background:${color}">
            <span>${di + 1}-${ai + 1}</span>
          </div>`,
        offset: new AMapCtor.Pixel(-16, -16),
      })
      marker.on('click', () => {
        infoWindow.setContent(
          `<div class="amap-infowindow">
             <b>${a.name}</b>
             <p>${a.address || ''}</p>
             <p>${a.description || ''}</p>
             <span>第 ${di + 1} 天 · ${a.visit_duration} 分钟</span>
           </div>`
        )
        infoWindow.open(map, marker.getPosition())
      })
      markers.push(marker)
      map.add(marker)
    })

    // 餐饮 marker（小圆点，不喧宾夺主）
    day.meals.forEach((m, mi) => {
      if (!m.location || typeof m.location.longitude !== 'number') return
      anyPoi = true
      const marker = new AMapCtor.Marker({
        position: [m.location.longitude, m.location.latitude],
        title: m.name,
        zIndex: 90,
        content: `<div class="amap-meal-marker" style="border-color:${color}"></div>`,
        offset: new AMapCtor.Pixel(-6, -6),
      })
      marker.on('click', () => {
        infoWindow.setContent(
          `<div class="amap-infowindow">
             <b>🍽️ ${m.name}</b>
             <p>${m.address || ''}${m.address && m.description ? ' · ' : ''}${m.description || ''}</p>
             <span>第 ${di + 1} 天 · ${mealTypeLabel(m.type)}</span>
           </div>`
        )
        infoWindow.open(map, marker.getPosition())
      })
      markers.push(marker)
      map.add(marker)
    })
  })

  if (anyPoi && markers.length) map.setFitView(markers, false, [60, 60, 60, 60])
}

function syncMap() {
  renderMarkers()
}

onMounted(() => {
  if (!plan.value) return
  nextTick(() => initMap())
})

onUnmounted(() => {
  if (map) map.destroy()
  map = null
})

// ------- 导出 -------
const contentRef = ref<HTMLElement>()

async function exportPNG() {
  if (!contentRef.value) return
  message.loading({ content: '正在导出 PNG...', key: 'export' })
  try {
    const canvas = await html2canvas(contentRef.value, { scale: 2, backgroundColor: '#f4f6fb', useCORS: true })
    const a = document.createElement('a')
    a.download = `旅行计划-${plan.value?.city || 'plan'}.png`
    a.href = canvas.toDataURL('image/png')
    a.click()
    message.success({ content: 'PNG 已导出', key: 'export' })
  } catch (e: any) {
    message.error({ content: '导出失败：' + (e?.message || ''), key: 'export' })
  }
}

async function exportPDF() {
  if (!contentRef.value) return
  message.loading({ content: '正在导出 PDF...', key: 'export' })
  try {
    const canvas = await html2canvas(contentRef.value, { scale: 2, backgroundColor: '#f4f6fb', useCORS: true })
    const img = canvas.toDataURL('image/jpeg', 0.95)
    const pdf = new jsPDF('p', 'mm', 'a4')
    const pageW = pdf.internal.pageSize.getWidth()
    const pageH = pdf.internal.pageSize.getHeight()
    const imgH = (canvas.height * pageW) / canvas.width
    let heightLeft = imgH
    let position = 0
    pdf.addImage(img, 'JPEG', 0, position, pageW, imgH)
    heightLeft -= pageH
    while (heightLeft > 0) {
      position -= pageH
      pdf.addPage()
      pdf.addImage(img, 'JPEG', 0, position, pageW, imgH)
      heightLeft -= pageH
    }
    pdf.save(`旅行计划-${plan.value?.city || 'plan'}.pdf`)
    message.success({ content: 'PDF 已导出', key: 'export' })
  } catch (e: any) {
    message.error({ content: '导出失败：' + (e?.message || ''), key: 'export' })
  }
}

// ------- 锚点高亮（简单 scroll-spy） -------
const activeAnchor = ref<string[]>(['overview'])
function onScroll() {
  const ids = ['overview', 'budget', 'map', 'itinerary', 'weather']
  let current = 'overview'
  for (const id of ids) {
    const el = document.getElementById(id)
    if (el && el.getBoundingClientRect().top <= 120) current = id
  }
  if (activeAnchor.value[0] !== current) activeAnchor.value = [current]
}
onMounted(() => window.addEventListener('scroll', onScroll, { passive: true }))
onUnmounted(() => window.removeEventListener('scroll', onScroll))
</script>

<style scoped>
.result-page {
  min-height: 100vh;
  background:
    radial-gradient(800px 400px at 100% 0%, rgba(199, 91, 156, 0.08), transparent 60%),
    radial-gradient(700px 400px at 0% 100%, rgba(43, 156, 219, 0.08), transparent 60%),
    #f4f6fb;
}

/* 空状态 */
.empty {
  min-height: 70vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.empty-ic { font-size: 64px; }
.empty h2 { font-size: 22px; color: var(--text-main); }
.empty p { color: var(--text-soft); }

/* 顶部栏 */
.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid rgba(30, 42, 69, 0.08);
}
.topbar-inner {
  max-width: 1240px;
  margin: 0 auto;
  padding: 14px 28px;
  display: flex;
  align-items: center;
  gap: 18px;
}
.topbar-title { display: flex; align-items: center; gap: 14px; }
.city-badge {
  padding: 6px 18px;
  border-radius: 12px;
  font-size: 20px;
  font-weight: 800;
  color: #fff;
  background: var(--grad-main);
  box-shadow: 0 10px 20px -10px rgba(71, 45, 112, 0.7);
}
.topbar-meta { display: flex; flex-direction: column; gap: 2px; }
.meta-date { font-weight: 600; color: var(--text-main); }
.meta-tag { font-size: 12px; color: var(--text-soft); }
.topbar-total { margin-left: auto; text-align: right; }
.topbar-total small { display: block; color: var(--text-soft); font-size: 12px; }
.topbar-total b { font-size: 24px; color: var(--coral); }
.topbar-actions { display: flex; gap: 8px; margin-left: 16px; }

/* 布局 */
.result-body {
  max-width: 1240px;
  margin: 0 auto;
  padding: 28px;
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 26px;
  align-items: start;
}
.side-nav-sticky { position: sticky; top: 84px; }
.nav-title { font-weight: 700; color: var(--text-main); margin-bottom: 10px; padding-left: 8px; }
.nav-menu {
  border-inline-end: none !important;
  border-radius: var(--radius-md);
  background: transparent;
}
.nav-menu :deep(.ant-menu-item) { border-radius: 10px; margin: 4px 0; }
.nav-menu :deep(a) { color: var(--text-soft); }
.nav-menu :deep(.ant-menu-item-selected) {
  background: linear-gradient(120deg, rgba(255, 183, 3, 0.14), rgba(255, 107, 107, 0.14));
}
.nav-menu :deep(.ant-menu-item-selected a) { color: var(--coral); font-weight: 600; }

/* 主体 */
.content { min-width: 0; display: flex; flex-direction: column; gap: 26px; }
.section { scroll-margin-top: 90px; }
.section.card { padding: 26px 30px; }
.sec-title { font-size: 20px; font-weight: 700; margin-bottom: 18px; display: flex; align-items: center; gap: 8px; }
.sec-title::before { content: ''; width: 5px; height: 20px; border-radius: 4px; background: var(--grad-gold); }

/* 概览 */
.overview-text { line-height: 1.9; color: var(--text-main); font-size: 15px; }
.quick-facts { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 22px; }
.fact {
  padding: 16px 12px;
  text-align: center;
  border-radius: var(--radius-md);
  background: #f7f9ff;
  border: 1px solid #eef1fa;
}
.fact-ic { display: block; font-size: 22px; }
.fact b { display: block; font-size: 20px; color: var(--text-main); margin-top: 4px; }
.fact small { color: var(--text-soft); }

/* 预算 */
.budget-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; }
.budget-card {
  padding: 18px 16px;
  border-radius: var(--radius-md);
  color: #fff;
  display: flex;
  flex-direction: column;
  gap: 6px;
  box-shadow: 0 14px 30px -14px rgba(0, 0, 0, 0.35);
}
.budget-ic { font-size: 22px; }
.budget-card small { opacity: 0.85; }
.budget-card b { font-size: 22px; }
.budget-card.total b { font-size: 26px; }

/* 地图 */
.map-container { width: 100%; height: 520px; border-radius: var(--radius-lg); overflow: hidden; box-shadow: var(--shadow-soft); }
.map-notice { margin-bottom: 14px; }
.map-legend { display: flex; gap: 16px; margin-top: 12px; flex-wrap: wrap; }
.legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-soft); }
.legend-item i { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.legend-item .legend-meal { width: 11px; height: 11px; border-radius: 50%; background: #fff; border: 2px solid #7b61ff; }
.legend-item .legend-hotel { width: 13px; height: 13px; border-radius: 4px; background: #fff; border: 2px solid #7b61ff; }

/* 时间线 */
.timeline { position: relative; padding: 12px 0; }
.timeline::before {
  content: '';
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 3px;
  transform: translateX(-1.5px);
  background: linear-gradient(180deg, var(--gold), var(--coral), var(--teal));
  border-radius: 3px;
  opacity: 0.5;
}
.tl-item {
  position: relative;
  width: 50%;
  padding: 10px 40px 10px 0;
}
.tl-item.right { margin-left: 50%; padding: 10px 0 10px 40px; }
.tl-dot {
  position: absolute;
  right: -20px;
  top: 24px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  font-weight: 700;
  box-shadow: 0 0 0 5px #fff, 0 8px 18px -6px rgba(0, 0, 0, 0.3);
  z-index: 2;
}
.tl-item.right .tl-dot { left: -20px; right: auto; }
.tl-card { padding: 22px 24px; transition: transform 0.25s; }
.tl-card:hover { transform: translateY(-3px); }

.day-head { margin-bottom: 16px; }
.day-badge {
  color: #fff;
  padding: 4px 12px;
  border-radius: 999px;
  font-weight: 600;
  font-size: 13px;
  margin-right: 8px;
}
.day-date { color: var(--text-soft); font-size: 13px; }
.day-desc { margin-top: 10px; color: var(--text-main); line-height: 1.7; font-size: 14px; }

.attr-list { display: flex; flex-direction: column; gap: 10px; }
.attr-row {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  background: #f7f9ff;
  border: 1px solid #eef1fa;
  align-items: flex-start;
}
.attr-img-wrap {
  position: relative;
  width: 84px; height: 84px;
  border-radius: 14px;
  overflow: hidden;
  flex-shrink: 0;
  background: linear-gradient(135deg, #ffe9c2, #ffd4b0);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.04);
}
.attr-img-ph {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 26px;
}
.attr-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.attr-idx {
  position: absolute;
  top: 6px; left: 6px;
  z-index: 2;
  width: 22px; height: 22px;
  border-radius: 8px;
  color: #fff;
  font-weight: 700;
  font-size: 12px;
  display: grid;
  place-items: center;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
}
.attr-main { flex: 1; min-width: 0; }
.attr-name { font-weight: 600; color: var(--text-main); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.attr-meta { display: flex; gap: 14px; margin-top: 5px; font-size: 12px; color: var(--text-soft); flex-wrap: wrap; }
.attr-desc { margin-top: 6px; font-size: 13px; color: var(--text-soft); line-height: 1.6; }
.attr-ops { display: flex; flex-direction: column; gap: 2px; }

.meal-section { margin-top: 14px; border-top: 1px dashed #e4e9f5; padding-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.meal-row { display: flex; align-items: flex-start; gap: 10px; font-size: 14px; }
.meal-info { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.meal-sub { font-size: 12px; color: var(--text-soft); line-height: 1.5; }
.meal-type {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: #fff;
  flex-shrink: 0;
}
.meal-breakfast { background: #f29a4e; }
.meal-lunch { background: #43c6ac; }
.meal-dinner { background: #7b61ff; }
.meal-snack { background: #2d9cdb; }
.meal-name { color: var(--text-main); }
.meal-cost { margin-left: auto; color: var(--text-soft); font-size: 12px; }

.hotel-card {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-radius: var(--radius-md);
  background: linear-gradient(120deg, rgba(123, 97, 255, 0.08), rgba(43, 156, 219, 0.08));
  border: 1px solid rgba(123, 97, 255, 0.2);
}
.hotel-ic { font-size: 24px; }
.hotel-main { flex: 1; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.hotel-title { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.hotel-title b { color: var(--text-main); }
.hotel-type { font-size: 12px; color: var(--text-soft); background: #f1f4ff; border-radius: 6px; padding: 1px 8px; }
.hotel-rating { font-size: 12px; color: #b8860b; background: #fff7e0; border-radius: 6px; padding: 1px 8px; }
.hotel-sub { font-size: 12px; color: var(--text-soft); }
.hotel-side { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; margin-left: 12px; flex-shrink: 0; }
.hotel-price-range { font-size: 12px; color: var(--text-soft); }
.hotel-cost { color: var(--coral); font-weight: 600; }

.day-foot { margin-top: 12px; font-size: 12px; color: var(--text-soft); display: flex; gap: 16px; flex-wrap: wrap; }

/* 天气 */
.weather-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px; }
.weather-card {
  padding: 18px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #ffffff, #f2f6ff);
  border: 1px solid #e8eefc;
  text-align: center;
}
.w-date { font-weight: 600; color: var(--text-main); font-size: 14px; }
.w-ic { font-size: 34px; margin: 8px 0; }
.w-weather { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--text-soft); }
.w-weather b { font-size: 15px; color: var(--text-main); }

.foot { text-align: center; color: var(--text-soft); font-size: 13px; padding: 24px 0; }

@media (max-width: 960px) {
  .result-body { grid-template-columns: 1fr; }
  .side-nav { display: none; }
  .budget-grid { grid-template-columns: repeat(3, 1fr); }
  .quick-facts { grid-template-columns: repeat(2, 1fr); }
  .tl-item, .tl-item.right { width: 100%; margin-left: 0; padding-left: 44px; padding-right: 0; }
  .timeline::before { left: 16px; }
  .tl-dot { left: 0 !important; right: auto !important; }
  .attr-img-wrap { width: 64px; height: 64px; }
}
</style>

<style>
/* 地图 Marker / InfoWindow 样式（非 scoped，作用于 AMap 动态 DOM） */
.amap-marker {
  width: 32px;
  height: 32px;
  border-radius: 50% 50% 50% 0;
  transform: rotate(-45deg);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 14px -4px rgba(0, 0, 0, 0.4);
}
.amap-marker span {
  transform: rotate(45deg);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
.amap-hotel-marker {
  width: 32px; height: 32px;
  border-radius: 10px;
  background: #fff;
  display: grid;
  place-items: center;
  font-size: 16px;
  box-shadow: 0 4px 12px -2px rgba(0, 0, 0, 0.3);
  border: 2.5px solid #7b61ff;
}
.amap-meal-marker {
  width: 12px; height: 12px;
  border-radius: 50%;
  background: #fff;
  border: 2.5px solid #7b61ff;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.85);
}
.amap-infowindow b { font-size: 14px; }
.amap-infowindow p { font-size: 12px; color: #666; margin: 4px 0; line-height: 1.5; }
.amap-infowindow span { font-size: 11px; color: #999; }
</style>
