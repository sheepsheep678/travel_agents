<template>
  <div class="result-page">
    <!-- 无数据占位 -->
    <div v-if="!plan" class="empty">
      <div class="empty-ic">🧳</div>
      <h2>还没有行程数据</h2>
      <p>先去填写你的旅行偏好，让旅迹智绘为你生成一份专属计划吧</p>
      <a-button type="primary" size="large" @click="$router.push('/quick-start')">去规划 →</a-button>
    </div>

    <template v-else>
      <!-- 顶部：品牌 + 行程 + 操作 + 章节导航 -->
      <header class="topbar">
        <div class="topbar-inner">
          <router-link to="/" class="brand">
            <span class="brand-seal">旅</span>
            <span class="brand-text">
              <b>旅迹智绘</b>
              <small>TRAVEL SKETCHBOOK</small>
            </span>
          </router-link>
          <div class="topbar-trip">
            <b>{{ plan.city }}</b>
            <span>{{ fmtDate(plan.start_date) }} — {{ fmtDate(plan.end_date) }} · 共 {{ days.length }} 天</span>
          </div>
          <div class="topbar-actions">
            <a-button @click="exportPNG">
              <template #icon><PictureOutlined /></template>PNG
            </a-button>
            <a-button @click="exportPDF">
              <template #icon><FilePdfOutlined /></template>PDF
            </a-button>
            <a-button @click="$router.push('/quick-start')">重新规划</a-button>
          </div>
        </div>
        <nav class="tabs" aria-label="章节导航">
          <a
            v-for="tab in tabs"
            :key="tab.id"
            :href="'#' + tab.id"
            :class="{ active: activeAnchor[0] === tab.id }"
            @click.prevent="scrollTo(tab.id)"
          >
            <small>{{ tab.en }}</small>
            <span>{{ tab.zh }}</span>
          </a>
        </nav>
      </header>

      <main ref="contentRef" class="sheet">
        <!-- 登机牌式总览 -->
        <section class="boarding">
          <div class="boarding-top">
            <span class="board-kicker">BOARDING · 旅行计划</span>
            <span class="board-days">{{ String(days.length).padStart(2, '0') }} DAYS</span>
          </div>

          <div class="board-ports">
            <div class="port">
              <span class="port-label">启程</span>
              <b class="port-date">{{ fmtDate(plan.start_date) }}</b>
              <span class="port-sub">{{ weekday(plan.start_date) }}</span>
            </div>
            <div class="port port-center">
              <span class="port-label">DESTINATION / 目的地</span>
              <b class="port-city">{{ plan.city }}</b>
              <span class="port-sub">共 {{ days.length }} 天 · {{ totalAttractions }} 处风景</span>
            </div>
            <div class="port port-right">
              <span class="port-label">返程</span>
              <b class="port-date">{{ fmtDate(plan.end_date) }}</b>
              <span class="port-sub">{{ weekday(plan.end_date) }}</span>
            </div>
          </div>

          <div class="board-track" aria-hidden="true">
            <span class="track-dot"></span>
            <span class="track-line"></span>
            <span class="track-mark">✦</span>
            <span class="track-line"></span>
            <span class="track-dot"></span>
          </div>

          <div class="board-bottom">
            <div class="board-countdown">
              <span>{{ countdown.label }}</span>
              <b>{{ countdown.text }}</b>
            </div>
            <dl class="board-facts">
              <div><dt>景点</dt><dd>{{ totalAttractions }}</dd></div>
              <div><dt>酒店</dt><dd>{{ totalHotels }}</dd></div>
              <div><dt>用餐</dt><dd>{{ totalMeals }}</dd></div>
              <div><dt>预算</dt><dd>¥{{ plan.budget?.total ?? 0 }}</dd></div>
            </dl>
          </div>
        </section>

        <!-- 车次票面：左右滑动切换 -->
        <section id="transit" class="transit">
          <header class="block-head transit-head">
            <div>
              <p class="kicker">TRANSIT</p>
              <h2 class="block-title">车次 · 航班</h2>
            </div>
            <span class="transit-source">12306 实时余票 · 暂未接入航班数据</span>
          </header>

          <div class="train-controls">
            <a-input
              v-model:value="fromCity"
              class="train-origin"
              placeholder="出发城市，如 北京"
              allow-clear
              @press-enter="searchTrains"
            />
            <div class="date-chips">
              <button
                type="button"
                class="date-chip"
                :class="{ active: trainDate === plan.start_date }"
                @click="pickTrainDate(plan.start_date)"
              >去程 · {{ fmtDate(plan.start_date) }}</button>
              <button
                type="button"
                class="date-chip"
                :class="{ active: trainDate === plan.end_date }"
                @click="pickTrainDate(plan.end_date)"
              >返程 · {{ fmtDate(plan.end_date) }}</button>
            </div>
            <a-button type="primary" :loading="trainLoading" @click="searchTrains">查车次</a-button>
          </div>

          <div v-if="trains.length" class="ticket-stage">
            <button type="button" class="ticket-arrow prev" aria-label="上一班" @click="prevTicket">←</button>

            <div
              class="ticket-viewport"
              @pointerdown="onTicketPointerDown"
              @pointerup="onTicketPointerUp"
              @pointercancel="onTicketPointerCancel"
            >
              <div class="ticket-track" :style="{ transform: `translateX(-${ticketIndex * 100}%)` }">
                <article v-for="(t, ti) in trains" :key="ti" class="train-ticket">
                  <div class="tt-top">
                    <span class="tt-kicker">12306 · 车次票面</span>
                    <span class="tt-index">{{ String(ti + 1).padStart(2, '0') }} / {{ String(trains.length).padStart(2, '0') }}</span>
                  </div>
                  <div class="tt-main">
                    <div class="tt-port">
                      <b class="tt-time">{{ t.start_time }}</b>
                      <span class="tt-station">{{ t.from_station }}</span>
                      <span class="tt-date">{{ fmtDate(t.start_date) }} {{ weekday(t.start_date) }}</span>
                    </div>
                    <div class="tt-route">
                      <span class="tt-code">{{ t.train_code }}</span>
                      <div class="tt-line"><i></i><span>→</span><i></i></div>
                      <span class="tt-duration">历时 {{ t.duration }}</span>
                    </div>
                    <div class="tt-port tt-right">
                      <b class="tt-time">{{ t.arrive_time }}</b>
                      <span class="tt-station">{{ t.to_station }}</span>
                      <span class="tt-date">{{ fmtDate(t.arrive_date) }} {{ weekday(t.arrive_date) }}</span>
                    </div>
                  </div>
                  <div class="tt-bottom">
                    <span class="tt-flags">{{ (t.flags || []).join(' · ') }}</span>
                    <div class="tt-seats">
                      <span v-for="(p, pi) in seatRows(t).slice(0, 3)" :key="pi" class="tt-seat">
                        {{ p.seat_name }} <b>{{ p.price }}</b>元 <em>{{ seatStatus(p.num) }}</em>
                      </span>
                    </div>
                  </div>
                </article>
              </div>
            </div>

            <button type="button" class="ticket-arrow next" aria-label="下一班" @click="nextTicket">→</button>
          </div>

          <div v-if="trains.length" class="ticket-dots">
            <button
              v-for="(t, ti) in trains"
              :key="ti"
              type="button"
              class="ticket-dot"
              :class="{ active: ti === ticketIndex }"
              :aria-label="`第 ${ti + 1} 班`"
              @click="ticketIndex = ti"
            ></button>
          </div>
          <p v-if="trains.length" class="ticket-hint">左右滑动或点箭头切换车次</p>

          <div v-else-if="trainLoading" class="ticket-empty">
            <span class="empty-ticket-kicker">QUERYING · 12306</span>
            <b>正在查询 {{ fromCity || '出发地' }} → {{ plan.city }} 的车次…</b>
            <small>首次查询可能需要几十秒</small>
          </div>

          <div v-else-if="trainError" class="ticket-empty error">
            <span class="empty-ticket-kicker">NO TICKET</span>
            <b>{{ trainError }}</b>
            <small>可换个出发城市或日期再试</small>
          </div>

          <div v-else class="ticket-empty">
            <span class="empty-ticket-kicker">TICKET</span>
            <b>输入出发城市，查询抵达 {{ plan.city }} 的车次</b>
            <small>支持高铁 / 动车 / 普速，数据来自 12306</small>
          </div>
        </section>

        <!-- 概览 -->
        <section id="overview" class="block">
          <header class="block-head">
            <p class="kicker">OVERVIEW</p>
            <h2 class="block-title">行程概览</h2>
          </header>
          <MarkdownBody class="lead" :content="plan.overall_suggestions" />
        </section>

        <!-- 预算 -->
        <section id="budget" class="block">
          <header class="block-head">
            <p class="kicker">BUDGET</p>
            <h2 class="block-title">预算明细</h2>
          </header>
          <div class="receipt">
            <div v-for="b in budgetItems" :key="b.key" class="receipt-row">
              <span class="receipt-ic">{{ b.icon }}</span>
              <span class="receipt-label">{{ b.label }}</span>
              <span class="receipt-leader"></span>
              <b class="receipt-amount">¥ {{ b.value }}</b>
            </div>
            <div class="receipt-total">
              <span>总预算</span>
              <b>¥ {{ plan.budget?.total ?? 0 }}</b>
            </div>
          </div>
        </section>

        <!-- 地图 -->
        <section id="map" class="block">
          <header class="block-head">
            <p class="kicker">ROUTE</p>
            <h2 class="block-title">路线地图</h2>
          </header>
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

        <!-- 每日行程：一天一张票 -->
        <section id="itinerary" class="block">
          <header class="block-head">
            <p class="kicker">ITINERARY</p>
            <h2 class="block-title">每日行程</h2>
          </header>
          <div class="day-list">
            <article v-for="(day, di) in days" :key="di" class="day-pass">
              <aside class="day-stub">
                <span class="stub-kicker">DAY</span>
                <b class="stub-no">{{ String(di + 1).padStart(2, '0') }}</b>
                <span class="stub-date">{{ fmtDate(day.date) }}</span>
                <span class="stub-week">{{ weekday(day.date) }}</span>
                <i class="stub-mark">✦</i>
              </aside>

              <div class="day-main">
                <MarkdownBody class="day-desc" :content="day.description" />

                <div class="stops">
                  <div v-for="(a, ai) in day.attractions" :key="ai" class="stop">
                    <span class="stop-node" :style="{ borderColor: dayColor(di) }">{{ ai + 1 }}</span>
                    <div class="stop-thumb">
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
                    <div class="stop-body">
                      <div class="stop-head">
                        <b>{{ a.name }}</b>
                        <a-tag v-if="a.category">{{ a.category }}</a-tag>
                      </div>
                      <div class="stop-meta">
                        <span>{{ a.visit_duration }} 分钟</span>
                        <span v-if="a.ticket_price">门票 ¥{{ a.ticket_price }}</span>
                        <span v-else>免费</span>
                        <span v-if="a.rating">★ {{ a.rating }}</span>
                      </div>
                      <p class="stop-desc">{{ a.description }}</p>
                    </div>
                    <div class="stop-ops">
                      <a-button size="small" type="text" title="上移" :disabled="ai === 0" @click="moveAttr(di, ai, -1)">
                        <ArrowUpOutlined />
                      </a-button>
                      <a-button size="small" type="text" title="下移" :disabled="ai === day.attractions.length - 1" @click="moveAttr(di, ai, 1)">
                        <ArrowDownOutlined />
                      </a-button>
                      <a-button size="small" type="text" title="删除" danger @click="removeAttr(di, ai)">
                        <DeleteOutlined />
                      </a-button>
                    </div>
                  </div>
                  <a-empty v-if="day.attractions.length === 0" description="当日暂无景点" :image="simpleEmpty" />
                </div>

                <div class="services" v-if="day.meals.length || day.hotel">
                  <div class="meal-row" v-for="(m, mi) in day.meals" :key="mi">
                    <span class="meal-type" :class="'meal-' + m.type">{{ mealTypeLabel(m.type) }}</span>
                    <div class="meal-info">
                      <span class="meal-name">{{ m.name }}</span>
                      <span v-if="m.address || m.description" class="meal-sub">
                        {{ m.address }}{{ m.address && m.description ? ' · ' : '' }}{{ m.description }}
                      </span>
                    </div>
                    <span class="meal-leader"></span>
                    <span class="meal-cost" v-if="m.estimated_cost">约 ¥{{ m.estimated_cost }}</span>
                  </div>

                  <div class="hotel-card" v-if="day.hotel">
                    <span class="hotel-ic">🏨</span>
                    <div class="hotel-main">
                      <div class="hotel-title">
                        <b>{{ day.hotel.name }}</b>
                        <span v-if="day.hotel.type" class="hotel-type">{{ day.hotel.type }}</span>
                        <span v-if="day.hotel.rating" class="hotel-rating">★ {{ day.hotel.rating }}</span>
                      </div>
                      <span class="hotel-sub">{{ day.hotel.distance || day.hotel.address || '住宿推荐' }}</span>
                    </div>
                    <div class="hotel-side">
                      <span v-if="day.hotel.price_range" class="hotel-price-range">{{ day.hotel.price_range }}</span>
                      <span v-if="day.hotel.estimated_cost" class="hotel-cost">¥{{ day.hotel.estimated_cost }}/晚</span>
                    </div>
                  </div>
                </div>

                <footer class="day-foot">
                  <span>🚇 交通：{{ day.transportation }}</span>
                  <span v-if="day.accommodation">🛏️ 住宿：{{ day.accommodation }}</span>
                </footer>
              </div>
            </article>
          </div>
        </section>

        <!-- 天气 -->
        <section id="weather" class="block">
          <header class="block-head">
            <p class="kicker">FORECAST</p>
            <h2 class="block-title">天气信息</h2>
          </header>
          <div class="weather-grid">
            <div v-for="w in plan.weather_info" :key="w.date" class="weather-card">
              <div class="w-head">
                <b>{{ fmtDate(w.date) }}</b>
                <span>{{ weekday(w.date) }}</span>
              </div>
              <div class="w-main">
                <span class="w-ic">{{ weatherIcon(w.day_weather) }}</span>
                <div>
                  <b>{{ w.day_weather || '暂无预报' }}</b>
                  <span class="w-temps">{{ w.day_temp }}° / {{ w.night_temp }}°</span>
                </div>
              </div>
              <p class="w-sub">
                <template v-if="w.night_weather">夜间 {{ w.night_weather }}</template>
                <template v-if="w.wind_direction || w.wind_power"> · {{ w.wind_direction }} {{ w.wind_power }}</template>
              </p>
            </div>
          </div>
        </section>

        <footer class="foot">✨ 由旅迹智绘绘制 · 祝你一路顺风</footer>
      </main>
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
import { PAPER } from '../constants/theme'
import { usePaperTheme } from '../composables/usePaperTheme'
import MarkdownBody from '../components/chat/MarkdownBody.vue'
import { searchTrainTickets } from '../services/api'
import type { TripPlan, DayPlan, Attraction, TrainTicket, TrainSeatPrice } from '../types'

usePaperTheme()

// ------- 数据 -------
const plan = computed<TripPlan | null>(() => tripStore.plan)
const days = reactive<DayPlan[]>([])
// 注意：plan 来自 reactive(tripStore)，其嵌套对象是 Proxy，不能用 structuredClone，
// 改用 JSON 深拷贝转成普通对象（计划数据本身是纯 JSON 结构）
if (plan.value) days.push(...(JSON.parse(JSON.stringify(plan.value.days)) as DayPlan[]))

const simpleEmpty = computed(() => Empty.PRESENTED_IMAGE_SIMPLE)

const DAY_COLORS = ['#b3402a', '#c78a3e', '#7c8a6d', '#5b6e8a', '#8a6d9a', '#a05b6e', '#4a6e5f', '#8a7a5b']

function dayColor(i: number): string {
  return DAY_COLORS[i % DAY_COLORS.length]
}

const totalAttractions = computed(() => days.reduce((s, d) => s + d.attractions.length, 0))
const totalHotels = computed(() => days.filter((d) => d.hotel).length)
const totalMeals = computed(() => days.reduce((s, d) => s + d.meals.length, 0))

const budgetItems = computed(() => {
  const b = plan.value?.budget
  return [
    { key: 'attractions', label: '景点门票', value: b?.total_attractions ?? 0, icon: '🎫' },
    { key: 'hotels', label: '酒店住宿', value: b?.total_hotels ?? 0, icon: '🏨' },
    { key: 'meals', label: '餐饮', value: b?.total_meals ?? 0, icon: '🍜' },
    { key: 'transport', label: '交通', value: b?.total_transportation ?? 0, icon: '🚕' },
  ]
})

function mealTypeLabel(t: string): string {
  return { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '小吃' }[t] || t
}

/* ------- 12306 车次票面 ------- */
const TRAIN_ORIGIN_KEY = 'lvji_train_origin'
const fromCity = ref('')
try {
  fromCity.value = localStorage.getItem(TRAIN_ORIGIN_KEY) || ''
} catch {
  /* 隐私模式忽略 */
}
const trainDate = ref(plan.value?.start_date || '')
const trains = ref<TrainTicket[]>([])
const trainLoading = ref(false)
const trainError = ref('')
const ticketIndex = ref(0)
let trainAbort: AbortController | null = null
let ticketDragX: number | null = null

function pickTrainDate(date: string) {
  trainDate.value = date
  if (fromCity.value.trim()) searchTrains()
}

async function searchTrains() {
  const from = fromCity.value.trim()
  const to = plan.value?.city || ''
  if (!from) {
    trainError.value = '请先填写出发城市'
    return
  }
  if (!to || !trainDate.value) return

  trainAbort?.abort()
  const controller = new AbortController()
  trainAbort = controller
  trainLoading.value = true
  trainError.value = ''
  trains.value = []
  ticketIndex.value = 0

  try {
    const response = await searchTrainTickets(
      { fromCity: from, toCity: to, date: trainDate.value },
      controller.signal,
    )
    trains.value = response.tickets || []
    ticketIndex.value = 0
    if (!trains.value.length) {
      trainError.value = response.message || '没有查询到相关车次'
    } else {
      try {
        localStorage.setItem(TRAIN_ORIGIN_KEY, from)
      } catch {
        /* ignore */
      }
    }
  } catch (e: any) {
    if (e?.name === 'AbortError' || e?.name === 'CanceledError') return
    trainError.value = e?.response?.data?.message || e?.message || '查询失败'
    trains.value = []
  } finally {
    if (trainAbort === controller) trainLoading.value = false
  }
}

function seatRows(t: TrainTicket): TrainSeatPrice[] {
  return (t.prices || [])
    .filter((p) => p && p.seat_name && p.price != null && p.price > 0)
    .sort((a, b) => (a.price ?? 0) - (b.price ?? 0))
}

function seatStatus(num?: number | string | null): string {
  if (num === null || num === undefined || num === '') return '余票未知'
  if (typeof num === 'number') return num > 0 ? `剩 ${num} 张` : '无票'
  if (num === '有' || num === '充足') return '有票'
  if (num === '无' || num === '--') return '无票'
  return String(num)
}

function prevTicket() {
  if (!trains.value.length) return
  ticketIndex.value = (ticketIndex.value - 1 + trains.value.length) % trains.value.length
}

function nextTicket() {
  if (!trains.value.length) return
  ticketIndex.value = (ticketIndex.value + 1) % trains.value.length
}

function onTicketPointerDown(event: PointerEvent) {
  ticketDragX = event.clientX
}

function onTicketPointerUp(event: PointerEvent) {
  if (ticketDragX == null) return
  const delta = event.clientX - ticketDragX
  ticketDragX = null
  if (Math.abs(delta) < 40) return
  if (delta < 0) nextTicket()
  else prevTicket()
}

function onTicketPointerCancel() {
  ticketDragX = null
}

onUnmounted(() => trainAbort?.abort())

/** YYYY-MM-DD → 6月1日（手账文案不露 ISO 格式；非该格式则原样返回） */
function fmtDate(s?: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s ?? '')
  return m ? `${Number(m[2])}月${Number(m[3])}日` : (s ?? '')
}

/** YYYY-MM-DD → 周一（无法解析时返回空串） */
function weekday(s?: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s ?? '')
  if (!m) return ''
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()] ?? ''
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function dayStartMs(s?: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s ?? '')
  if (!m) return null
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime()
}

// 登机牌上的实时倒计时：出发前按秒走，出发后显示当前第几天
const DAY_MS = 86_400_000
const now = ref(Date.now())
const clock = window.setInterval(() => { now.value = Date.now() }, 1000)
onUnmounted(() => window.clearInterval(clock))

const countdown = computed(() => {
  const start = dayStartMs(plan.value?.start_date)
  const end = dayStartMs(plan.value?.end_date)
  const total = days.length
  if (start == null) return { label: '行程', text: `共 ${total} 天` }
  const t = now.value
  if (t < start) {
    const diff = start - t
    const d = Math.floor(diff / DAY_MS)
    const rest = diff % DAY_MS
    const h = Math.floor(rest / 3_600_000)
    const m = Math.floor((rest % 3_600_000) / 60_000)
    const s = Math.floor((rest % 60_000) / 1000)
    return { label: '距离出发还剩', text: `${d}天 ${pad2(h)}:${pad2(m)}:${pad2(s)}` }
  }
  if (end != null && t > end + DAY_MS - 1) {
    return { label: '旅程状态', text: `已返程 · 共 ${total} 天` }
  }
  const dayNo = end != null ? Math.min(total, Math.floor((t - start) / DAY_MS) + 1) : 1
  return { label: '旅程进行中', text: `第 ${dayNo} 天 / 共 ${total} 天` }
})

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
let polylines: any[] = []

async function initMap() {
  const key = import.meta.env.VITE_AMAP_WEB_JS_KEY
  if (!key) {
    mapNotice.value = '地图密钥未配置，暂时无法显示地图'
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
    mapNotice.value = '地图加载失败，请检查地图密钥配置'
  }
}

function renderMarkers() {
  if (!map) return
  markers.forEach((m) => map.remove(m))
  markers = []
  polylines.forEach((p) => map.remove(p))
  polylines = []

  let anyPoi = false
  days.forEach((day, di) => {
    const color = dayColor(di)
    const dayPath: number[][] = []

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
      dayPath.push([a.location.longitude, a.location.latitude])
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

    // 当天景点连线：按行程顺序连接景点（只连景点，不含酒店/餐饮），虚线带方向箭头
    if (dayPath.length >= 2) {
      const line = new AMapCtor.Polyline({
        path: dayPath,
        strokeColor: color,
        strokeWeight: 4,
        strokeOpacity: 0.75,
        strokeStyle: 'dashed',
        lineJoin: 'round',
        showDir: true,
        zIndex: 50,
      })
      map.add(line)
      polylines.push(line)
    }
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
  message.loading({ content: '正在导出 PNG…', key: 'export' })
  try {
    const canvas = await html2canvas(contentRef.value, { scale: 2, backgroundColor: PAPER, useCORS: true })
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
  message.loading({ content: '正在导出 PDF…', key: 'export' })
  try {
    const canvas = await html2canvas(contentRef.value, { scale: 2, backgroundColor: PAPER, useCORS: true })
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

// ------- 章节导航 / 锚点高亮（简单 scroll-spy） -------
const tabs = [
  { id: 'overview', en: 'OVERVIEW', zh: '概览' },
  { id: 'budget', en: 'BUDGET', zh: '预算' },
  { id: 'map', en: 'ROUTE', zh: '地图' },
  { id: 'itinerary', en: 'ITINERARY', zh: '行程' },
  { id: 'weather', en: 'FORECAST', zh: '天气' },
]

const activeAnchor = ref<string[]>(['overview'])

function scrollTo(id: string) {
  activeAnchor.value = [id]
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function onScroll() {
  let current = 'overview'
  for (const tab of tabs) {
    const el = document.getElementById(tab.id)
    if (el && el.getBoundingClientRect().top <= 150) current = tab.id
  }
  if (activeAnchor.value[0] !== current) activeAnchor.value = [current]
}
onMounted(() => window.addEventListener('scroll', onScroll, { passive: true }))
onUnmounted(() => window.removeEventListener('scroll', onScroll))

// 结果页同样套用手账纸墨主题（usePaperTheme 提供 --paper/--ink 等 token 与弹层主题）
</script>

<style scoped>
/* ========== 结果页：登机牌 / 车票式排版 ========== */
.result-page {
  min-height: 100vh;
  position: relative;
  background:
    radial-gradient(1200px 700px at 10% -6%, rgba(154, 106, 62, 0.12), transparent 60%),
    radial-gradient(900px 600px at 95% 104%, rgba(154, 106, 62, 0.09), transparent 55%),
    var(--paper);
  color: var(--ink);
  font-family: var(--font);
  -webkit-font-smoothing: antialiased;
  --board: #1c2b34;
  --board-2: #263b47;
  --board-ink: #efe7d6;
  --board-dim: rgba(239, 231, 214, 0.58);
  --board-line: rgba(239, 231, 214, 0.2);
}

/* 空状态 */
.empty {
  min-height: 70vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  text-align: center;
}
.empty-ic { font-size: 64px; }
.empty h2 { font-size: 24px; font-family: var(--display); font-weight: 400; color: var(--ink); }
.empty p { color: var(--ink-soft); }
.result-page :deep(.ant-btn-primary) {
  background: var(--seal);
  border: none;
  box-shadow: none;
  font-family: var(--font);
  letter-spacing: 0.04em;
}
.result-page :deep(.ant-btn-primary:hover) { background: var(--earth); opacity: 1; }

/* ---- 顶部栏 ---- */
.topbar {
  position: sticky;
  top: 0;
  z-index: 30;
  background: rgba(236, 231, 220, 0.9);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--hairline);
}
.topbar-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 12px 28px;
  display: flex;
  align-items: center;
  gap: 20px;
}
.brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--ink); }
.brand-seal {
  width: 34px;
  height: 34px;
  border-radius: 6px;
  display: grid;
  place-items: center;
  background: var(--seal);
  color: #fff;
  font-family: var(--display);
  font-size: 19px;
  box-shadow: 0 8px 18px -12px rgba(179, 64, 42, 0.8);
}
.brand-text { display: flex; flex-direction: column; line-height: 1.15; }
.brand-text b { font-family: var(--display); font-weight: 400; font-size: 18px; letter-spacing: 0.06em; }
.brand-text small { font-size: 8px; letter-spacing: 0.22em; color: var(--ink-faint); }
.topbar-trip { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; }
.topbar-trip b { font-family: var(--display); font-weight: 400; font-size: 17px; letter-spacing: 0.04em; }
.topbar-trip span { font-size: 11px; color: var(--ink-soft); letter-spacing: 0.05em; }
.topbar-actions { display: flex; gap: 8px; margin-left: auto; }
.topbar-actions :deep(.ant-btn) {
  border: 1px solid var(--hairline);
  color: var(--ink-soft);
  background: transparent;
  box-shadow: none;
  font-family: var(--font);
}
.topbar-actions :deep(.ant-btn:hover) { color: var(--ink); border-color: var(--ink-soft); }

/* ---- 章节导航（横向） ---- */
.tabs {
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 28px 10px;
  display: flex;
  justify-content: center;
  gap: 4px;
  overflow-x: auto;
  scrollbar-width: none;
}
.tabs::-webkit-scrollbar { display: none; }
.tabs a {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 7px 18px;
  border-radius: 999px;
  color: var(--ink-soft);
  text-decoration: none;
  white-space: nowrap;
  transition: background 0.2s, color 0.2s;
}
.tabs small { font-size: 8px; letter-spacing: 0.2em; opacity: 0.72; }
.tabs span { font-size: 13px; }
.tabs a:hover { background: rgba(43, 39, 33, 0.06); color: var(--ink); }
.tabs a.active { background: var(--board); color: var(--board-ink); }
.tabs a.active small { opacity: 0.6; }

/* ---- 主体 ---- */
.sheet { max-width: 1120px; margin: 0 auto; padding: 30px 28px 40px; }

/* ---- 登机牌总览 ---- */
.boarding {
  position: relative;
  overflow: hidden;
  border-radius: 22px;
  padding: 28px 36px 24px;
  color: var(--board-ink);
  background:
    radial-gradient(700px 320px at 88% -20%, rgba(255, 255, 255, 0.08), transparent 60%),
    linear-gradient(135deg, var(--board-2), var(--board) 58%);
  box-shadow: 0 34px 70px -46px rgba(28, 43, 52, 0.85);
}
.boarding::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image: repeating-linear-gradient(115deg, rgba(255, 255, 255, 0.028) 0 1px, transparent 1px 11px);
}
.boarding-top { display: flex; align-items: center; justify-content: space-between; }
.board-kicker { font-size: 10px; letter-spacing: 0.28em; color: var(--board-dim); }
.board-days { font-size: 10px; letter-spacing: 0.24em; color: var(--board-dim); }

.board-ports {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: end;
  gap: 28px;
  margin-top: 22px;
}
.port { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.port-center { align-items: center; text-align: center; }
.port-right { align-items: flex-end; text-align: right; }
.port-label { font-size: 9px; letter-spacing: 0.24em; color: var(--board-dim); }
.port-date { font-family: var(--display); font-weight: 400; font-size: 34px; line-height: 1.1; }
.port-city {
  font-family: var(--display);
  font-weight: 400;
  font-size: 64px;
  line-height: 1.05;
  letter-spacing: 0.02em;
}
.port-sub { font-size: 11px; letter-spacing: 0.08em; color: var(--board-dim); }

.board-track { display: flex; align-items: center; gap: 10px; margin: 20px 0; }
.track-dot { width: 7px; height: 7px; border-radius: 50%; border: 1.5px solid var(--board-ink); flex-shrink: 0; }
.track-line {
  flex: 1;
  height: 1px;
  background: repeating-linear-gradient(90deg, var(--board-line) 0 3px, transparent 3px 7px);
}
.track-mark { font-size: 12px; color: var(--board-dim); }

.board-bottom {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding-top: 20px;
  border-top: 1px dashed var(--board-line);
}
.board-countdown { display: flex; flex-direction: column; gap: 5px; }
.board-countdown span { font-size: 10px; letter-spacing: 0.2em; color: var(--board-dim); }
.board-countdown b { font-family: var(--display); font-weight: 400; font-size: 30px; letter-spacing: 0.03em; }
.board-facts { display: flex; gap: 32px; }
.board-facts div { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.board-facts dt { font-size: 9px; letter-spacing: 0.2em; color: var(--board-dim); }
.board-facts dd { font-family: var(--display); font-size: 19px; }

/* ---- 车次票面 ---- */
.transit { margin-top: 28px; scroll-margin-top: 150px; }
.transit-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.transit-source { padding-bottom: 8px; font-size: 10px; letter-spacing: 0.12em; color: var(--ink-faint); white-space: nowrap; }
.train-controls { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
.train-origin { max-width: 220px; }
.train-origin :deep(.ant-input) {
  background: rgba(255, 252, 244, 0.55);
  border-color: var(--hairline);
  color: var(--ink);
  font-family: var(--font);
}
.train-origin :deep(.ant-input::placeholder) { color: var(--ink-faint); }
.date-chips { display: flex; gap: 6px; }
.date-chip {
  padding: 7px 12px;
  border: 1px solid var(--hairline);
  border-radius: 999px;
  background: transparent;
  color: var(--ink-soft);
  font-family: var(--font);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s, background 0.2s;
}
.date-chip:hover { border-color: var(--ink-soft); color: var(--ink); }
.date-chip.active { background: var(--board); border-color: var(--board); color: var(--board-ink); }
.train-controls :deep(.ant-btn-primary) {
  background: var(--seal);
  border: none;
  box-shadow: none;
  font-family: var(--font);
}
.train-controls :deep(.ant-btn-primary:hover) { background: var(--earth); }

.ticket-stage { display: flex; align-items: center; gap: 12px; }
.ticket-viewport {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  border-radius: 18px;
  touch-action: pan-y;
  cursor: grab;
  user-select: none;
}
.ticket-viewport:active { cursor: grabbing; }
.ticket-track { display: flex; transition: transform 0.38s cubic-bezier(0.22, 0.61, 0.36, 1); }
.train-ticket {
  position: relative;
  flex: 0 0 100%;
  box-sizing: border-box;
  min-height: 214px;
  padding: 22px 28px 20px;
  border-radius: 18px;
  overflow: hidden;
  color: var(--board-ink);
  background:
    radial-gradient(620px 280px at 90% -20%, rgba(255, 255, 255, 0.07), transparent 60%),
    linear-gradient(135deg, var(--board-2), var(--board) 60%);
  box-shadow: 0 28px 54px -44px rgba(28, 43, 52, 0.85);
}
.train-ticket::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image: repeating-linear-gradient(115deg, rgba(255, 255, 255, 0.028) 0 1px, transparent 1px 11px);
}
.tt-top { display: flex; align-items: center; justify-content: space-between; }
.tt-kicker { font-size: 9px; letter-spacing: 0.26em; color: var(--board-dim); }
.tt-index { font-size: 9px; letter-spacing: 0.22em; color: var(--board-dim); }
.tt-main {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: end;
  gap: 22px;
  margin-top: 20px;
}
.tt-port { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tt-right { align-items: flex-end; text-align: right; }
.tt-time { font-family: var(--display); font-weight: 400; font-size: 38px; line-height: 1; }
.tt-station { font-size: 15px; letter-spacing: 0.03em; }
.tt-date { font-size: 10px; letter-spacing: 0.08em; color: var(--board-dim); }
.tt-route { display: flex; flex-direction: column; align-items: center; gap: 6px; padding-bottom: 4px; }
.tt-code { font-size: 12px; letter-spacing: 0.16em; color: var(--board-ink); }
.tt-line { display: flex; align-items: center; gap: 8px; width: 150px; }
.tt-line i { flex: 1; height: 1px; background: repeating-linear-gradient(90deg, var(--board-line) 0 3px, transparent 3px 7px); }
.tt-line span { font-size: 12px; color: var(--board-dim); }
.tt-duration { font-size: 10px; color: var(--board-dim); }
.tt-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px dashed var(--board-line);
}
.tt-flags { font-size: 9px; letter-spacing: 0.14em; color: var(--board-dim); white-space: nowrap; }
.tt-seats { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; justify-content: flex-end; }
.tt-seat { font-size: 11px; color: var(--board-dim); white-space: nowrap; }
.tt-seat b { font-family: var(--display); font-weight: 400; font-size: 15px; color: var(--board-ink); }
.tt-seat em { font-style: normal; color: rgba(239, 231, 214, 0.45); }

.ticket-arrow {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--hairline);
  background: rgba(255, 252, 244, 0.6);
  color: var(--ink-soft);
  font-size: 15px;
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s;
}
.ticket-arrow:hover { color: var(--ink); border-color: var(--ink-soft); }
.ticket-dots { display: flex; justify-content: center; gap: 6px; margin-top: 14px; }
.ticket-dot {
  width: 6px;
  height: 6px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: var(--hairline);
  cursor: pointer;
  transition: width 0.2s, background 0.2s;
}
.ticket-dot.active { width: 18px; border-radius: 999px; background: var(--board); }
.ticket-hint { margin-top: 8px; text-align: center; font-size: 10px; letter-spacing: 0.08em; color: var(--ink-faint); }

.ticket-empty {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 30px 26px;
  border: 1px dashed var(--hairline);
  border-radius: 18px;
  background: rgba(255, 252, 244, 0.42);
  text-align: center;
}
.empty-ticket-kicker { font-size: 9px; letter-spacing: 0.3em; color: var(--earth); }
.ticket-empty b { font-family: var(--display); font-weight: 400; font-size: 22px; color: var(--ink); }
.ticket-empty small { font-size: 12px; color: var(--ink-soft); }
.ticket-empty.error { border-color: rgba(179, 64, 42, 0.35); background: rgba(179, 64, 42, 0.04); }
.ticket-empty.error .empty-ticket-kicker { color: var(--seal); }

/* ---- 通用区块 ---- */
.block { margin-top: 56px; scroll-margin-top: 150px; }
.block-head { margin-bottom: 20px; }
.kicker { font-size: 9px; letter-spacing: 0.3em; color: var(--earth); margin-bottom: 6px; }
.block-title {
  font-family: var(--display);
  font-weight: 400;
  font-size: 34px;
  letter-spacing: 0.02em;
  color: var(--ink);
}
.block-head::after {
  content: '';
  display: block;
  width: 44px;
  height: 2px;
  margin-top: 14px;
  background: var(--seal);
}
.lead { max-width: 820px; font-size: 16px; line-height: 2; color: var(--ink); }
.lead :deep(p) { margin: 0 0 0.65em; }
.lead :deep(p:last-child) { margin-bottom: 0; }
.lead :deep(ul),
.lead :deep(ol) { margin: 0.3em 0 0.8em; padding-left: 1.35em; }
.lead :deep(li) { margin: 0.15em 0; }
.lead :deep(strong) { font-weight: 600; color: var(--ink); }

/* ---- 预算：小票 ---- */
.receipt {
  max-width: 720px;
  padding: 26px 30px;
  border-radius: 14px;
  background: rgba(255, 252, 244, 0.68);
  border: 1px solid var(--hairline);
  box-shadow: 0 20px 44px -36px rgba(43, 39, 33, 0.55);
}
.receipt-row { display: flex; align-items: baseline; gap: 10px; padding: 10px 0; font-size: 14px; }
.receipt-row + .receipt-row { border-top: 1px dashed rgba(43, 39, 33, 0.1); }
.receipt-ic { width: 20px; flex-shrink: 0; text-align: center; font-size: 16px; }
.receipt-label { width: 76px; flex-shrink: 0; color: var(--ink-soft); }
.receipt-leader { flex: 1; min-width: 24px; border-bottom: 1px dotted var(--ink-faint); transform: translateY(-3px); }
.receipt-amount {
  width: 110px;
  flex-shrink: 0;
  text-align: right;
  font-family: var(--display);
  font-weight: 400;
  font-size: 18px;
  color: var(--ink);
}
.receipt-total {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 16px;
  border-top: 2px solid var(--ink);
}
.receipt-total span { font-size: 11px; letter-spacing: 0.18em; color: var(--ink-soft); }
.receipt-total b { font-family: var(--display); font-weight: 400; font-size: 34px; color: var(--seal); }

/* ---- 地图 ---- */
.map-notice { margin-bottom: 14px; }
.map-notice :deep(.ant-alert) { background: rgba(154, 106, 62, 0.08); border: 1px solid rgba(154, 106, 62, 0.25); }
.map-container {
  width: 100%;
  height: 480px;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--hairline);
}
.map-legend { display: flex; gap: 18px; margin-top: 14px; flex-wrap: wrap; }
.legend-item { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-soft); }
.legend-item i { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.legend-item .legend-meal { width: 11px; height: 11px; border-radius: 50%; background: var(--paper); border: 2px solid var(--earth); }
.legend-item .legend-hotel { width: 13px; height: 13px; border-radius: 4px; background: var(--paper); border: 2px solid var(--earth); }

/* ---- 每日行程：一天一张票 ---- */
.day-list { display: flex; flex-direction: column; gap: 22px; }
.day-pass {
  display: grid;
  grid-template-columns: 154px minmax(0, 1fr);
  border-radius: 16px;
  overflow: hidden;
  background: rgba(255, 252, 244, 0.62);
  border: 1px solid var(--hairline);
  box-shadow: 0 24px 50px -44px rgba(43, 39, 33, 0.6);
  transition: transform 0.25s, box-shadow 0.25s;
}
.day-pass:hover { transform: translateY(-2px); box-shadow: 0 30px 54px -42px rgba(43, 39, 33, 0.62); }
.day-stub {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 22px 20px;
  color: var(--board-ink);
  background: linear-gradient(160deg, var(--board-2), var(--board));
  border-right: 1px dashed var(--board-line);
}
.day-stub::before,
.day-stub::after {
  content: '';
  position: absolute;
  right: -9px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--paper);
}
.day-stub::before { top: -9px; }
.day-stub::after { bottom: -9px; }
.stub-kicker { font-size: 9px; letter-spacing: 0.3em; color: var(--board-dim); }
.stub-no { font-family: var(--display); font-weight: 400; font-size: 56px; line-height: 1; }
.stub-date { margin-top: 6px; font-size: 14px; }
.stub-week { font-size: 10px; letter-spacing: 0.18em; color: var(--board-dim); }
.stub-mark {
  margin-top: auto;
  width: 24px;
  height: 24px;
  border: 1px solid var(--board-line);
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 10px;
  font-style: normal;
  color: var(--board-dim);
}

.day-main { min-width: 0; padding: 24px 30px 22px; }
.day-desc { margin-bottom: 18px; font-size: 15px; line-height: 1.8; color: var(--ink); }
.day-desc :deep(p) { margin: 0 0 0.45em; }
.day-desc :deep(p:last-child) { margin-bottom: 0; }
.day-desc :deep(ul),
.day-desc :deep(ol) { margin: 0.25em 0 0.6em; padding-left: 1.35em; }
.day-desc :deep(li) { margin: 0.1em 0; }

.stops { display: flex; flex-direction: column; gap: 18px; }
.stop {
  position: relative;
  display: grid;
  grid-template-columns: 26px 88px minmax(0, 1fr) auto;
  gap: 14px;
  align-items: start;
}
.stop::before {
  content: '';
  position: absolute;
  left: 12.5px;
  top: 30px;
  bottom: -24px;
  border-left: 1px dashed var(--hairline);
}
.stop:last-child::before { display: none; }
.stop-node {
  width: 26px;
  height: 26px;
  margin-top: 2px;
  border-radius: 50%;
  border: 1.5px solid var(--earth);
  background: rgba(255, 252, 244, 0.9);
  color: var(--ink-soft);
  font-size: 11px;
  display: grid;
  place-items: center;
  z-index: 1;
}
.stop-thumb {
  position: relative;
  width: 88px;
  height: 88px;
  border-radius: 10px;
  overflow: hidden;
  background: linear-gradient(135deg, #efe6d6, #e2d5bd);
  box-shadow: inset 0 0 0 1px var(--hairline);
}
.attr-img-ph {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 26px;
  opacity: 0.7;
}
.attr-img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.stop-body { min-width: 0; padding-top: 1px; }
.stop-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.stop-head b { font-size: 16px; font-weight: 600; color: var(--ink); }
.stop-head :deep(.ant-tag) {
  margin-inline-end: 0;
  padding: 0 8px;
  border: none;
  border-radius: 999px;
  background: rgba(154, 106, 62, 0.12);
  color: var(--earth);
  font-size: 11px;
}
.stop-meta { display: flex; align-items: center; margin-top: 5px; font-size: 12px; color: var(--ink-soft); flex-wrap: wrap; }
.stop-meta span + span::before { content: '·'; margin: 0 8px; color: var(--ink-faint); }
.stop-desc {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.65;
  color: var(--ink-soft);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.stop-ops { display: flex; gap: 2px; opacity: 0; transition: opacity 0.2s; }
.stop:hover .stop-ops,
.stop:focus-within .stop-ops { opacity: 1; }
.stop-ops :deep(.ant-btn) { color: var(--ink-faint); }
.stop-ops :deep(.ant-btn:hover) { color: var(--ink); }
.stop-ops :deep(.ant-btn-dangerous) { color: var(--seal); }
.stops :deep(.ant-empty) { margin: 4px 0; }

/* 餐饮 / 酒店：票面附加服务 */
.services {
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px dashed var(--hairline);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.meal-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.meal-type {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  color: #fff;
  flex-shrink: 0;
}
.meal-breakfast { background: #c78a3e; }
.meal-lunch { background: #7c8a6d; }
.meal-dinner { background: #5b6e8a; }
.meal-snack { background: #8a6d9a; }
.meal-info { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.meal-name { color: var(--ink); white-space: nowrap; }
.meal-sub { font-size: 11px; color: var(--ink-soft); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meal-leader { flex: 1; min-width: 20px; border-bottom: 1px dotted var(--ink-faint); transform: translateY(-3px); }
.meal-cost { font-size: 12px; color: var(--ink-soft); white-space: nowrap; }

.hotel-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(154, 106, 62, 0.06);
  border: 1px solid rgba(154, 106, 62, 0.18);
}
.hotel-ic { font-size: 20px; }
.hotel-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.hotel-title { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.hotel-title b { color: var(--ink); font-size: 13px; }
.hotel-type { font-size: 11px; color: var(--ink-soft); background: rgba(43, 39, 33, 0.05); border-radius: 6px; padding: 0 7px; }
.hotel-rating { font-size: 11px; color: #8a6a2e; background: rgba(154, 106, 62, 0.12); border-radius: 6px; padding: 0 7px; }
.hotel-sub { font-size: 11px; color: var(--ink-soft); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hotel-side { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex-shrink: 0; }
.hotel-price-range { font-size: 11px; color: var(--ink-soft); }
.hotel-cost { font-size: 13px; color: var(--seal); font-weight: 600; }

.day-foot {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed var(--hairline);
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--ink-soft);
}

/* ---- 天气 ---- */
.weather-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; }
.weather-card {
  padding: 18px 20px;
  border-radius: 12px;
  background: rgba(255, 252, 244, 0.55);
  border: 1px solid var(--hairline);
}
.w-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; padding-bottom: 10px; border-bottom: 1px dashed var(--hairline); }
.w-head b { font-family: var(--display); font-weight: 400; font-size: 17px; color: var(--ink); }
.w-head span { font-size: 10px; letter-spacing: 0.14em; color: var(--ink-faint); }
.w-main { display: flex; align-items: center; gap: 14px; margin-top: 12px; }
.w-ic { font-size: 34px; }
.w-main b { display: block; font-family: var(--display); font-weight: 400; font-size: 20px; color: var(--ink); }
.w-temps { font-size: 12px; color: var(--ink-soft); }
.w-sub { margin-top: 10px; font-size: 11px; line-height: 1.6; color: var(--ink-soft); }

.foot {
  margin-top: 64px;
  padding: 26px 0 10px;
  border-top: 1px solid var(--hairline);
  text-align: center;
  color: var(--ink-faint);
  font-size: 12px;
  letter-spacing: 0.08em;
}

/* ---- 响应式 ---- */
@media (max-width: 1024px) {
  .topbar-trip { display: none; }
  .topbar-inner,
  .tabs { padding-left: 20px; padding-right: 20px; }
  .sheet { padding: 24px 20px 32px; }
  .port-city { font-size: 54px; }
  .day-pass { grid-template-columns: 132px minmax(0, 1fr); }
}

@media (max-width: 820px) {
  .boarding { padding: 24px; }
  .board-ports { grid-template-columns: 1fr 1fr; gap: 16px; }
  .port-center { grid-column: 1 / -1; order: -1; align-items: flex-start; text-align: left; }
  .port-city { font-size: 48px; }
  .board-bottom { flex-direction: column; align-items: flex-start; gap: 18px; }
  .board-facts { width: 100%; justify-content: space-between; gap: 12px; }
  .board-facts div { align-items: flex-start; }
  .day-pass { grid-template-columns: 1fr; }
  .day-stub {
    flex-direction: row;
    align-items: baseline;
    gap: 12px;
    padding: 16px 20px;
    border-right: none;
    border-bottom: 1px dashed var(--board-line);
  }
  .day-stub::before,
  .day-stub::after { display: none; }
  .stub-no { font-size: 38px; }
  .stub-date { margin-top: 0; }
  .stub-mark { margin: 0 0 0 auto; align-self: center; }
  .day-main { padding: 20px; }
  .stop { grid-template-columns: 24px 68px minmax(0, 1fr) auto; gap: 10px; }
  .stop-thumb { width: 68px; height: 68px; }
  .stop-ops { opacity: 1; }
  .tabs { justify-content: flex-start; }
  .brand-text small { display: none; }
  .transit-head { flex-direction: column; align-items: flex-start; gap: 4px; }
  .transit-source { padding-bottom: 0; }
  .train-origin { max-width: none; flex: 1 1 100%; }
  .tt-time { font-size: 30px; }
  .tt-line { width: 96px; }
}

@media (max-width: 560px) {
  .topbar-inner { gap: 10px; }
  .brand-text b { font-size: 16px; }
  .topbar-actions { gap: 4px; }
  .topbar-actions :deep(.ant-btn) { padding-inline: 8px; }
  .port-date { font-size: 22px; }
  .board-countdown b { font-size: 22px; }
  .board-facts dd { font-size: 14px; }
  .block-title { font-size: 28px; }
  .stop { grid-template-columns: 24px minmax(0, 1fr) auto; }
  .stop-thumb { display: none; }
  .meal-info { flex-direction: column; align-items: flex-start; gap: 0; }
  .meal-sub { max-width: 100%; }
  .ticket-arrow { display: none; }
  .train-ticket { padding: 18px 20px; }
  .tt-main { gap: 12px; }
  .tt-time { font-size: 24px; }
  .tt-station { font-size: 13px; }
  .tt-date { font-size: 9px; }
  .tt-bottom { flex-direction: column; align-items: flex-start; gap: 8px; }
  .tt-seats { justify-content: flex-start; }
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
  border: 2.5px solid #9a6a3e;
}
.amap-meal-marker {
  width: 12px; height: 12px;
  border-radius: 50%;
  background: #fff;
  border: 2.5px solid #9a6a3e;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.85);
}
.amap-infowindow b { font-size: 14px; color: #2b2721; }
.amap-infowindow p { font-size: 12px; color: rgba(43, 39, 33, 0.6); margin: 4px 0; line-height: 1.5; }
.amap-infowindow span { font-size: 11px; color: rgba(43, 39, 33, 0.4); }
</style>
