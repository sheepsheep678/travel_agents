<template>
  <div class="home">
    <!-- 背景装饰 -->
    <div class="blob blob-1"></div>
    <div class="blob blob-2"></div>
    <div class="blob blob-3"></div>
    <div class="stars" aria-hidden="true"></div>

    <div class="home-inner">
      <!-- 左侧品牌区 -->
      <section class="brand fade-up">
        <div class="brand-badge">
          <span class="dot"></span>
          AI 驱动的行程规划引擎
        </div>
        <h1 class="brand-title">
          让 AI 为你规划<br />
          <span class="grad-text">一段心动旅程</span>
        </h1>
        <p class="brand-sub">
          基于 LangGraph 多智能体编排，自动检索高德真实景点与酒店、查询当地天气，
          为你量身定制每一天的完美行程。
        </p>

        <ul class="features">
          <li>
            <span class="feat-ic">🗺️</span>
            <div>
              <b>真实 POI 数据</b>
              <small>调用高德地图检索景点、酒店与周边信息</small>
            </div>
          </li>
          <li>
            <span class="feat-ic">🌤️</span>
            <div>
              <b>智能天气整合</b>
              <small>结合目的地天气给出出行与穿衣建议</small>
            </div>
          </li>
          <li>
            <span class="feat-ic">💡</span>
            <div>
              <b>贴心预算规划</b>
              <small>门票 / 住宿 / 餐饮 / 交通费用一目了然</small>
            </div>
          </li>
        </ul>
      </section>

      <!-- 右侧表单卡 -->
      <section class="panel glass-card fade-up" style="animation-delay: 0.12s">
        <!-- 表单模式 -->
        <template v-if="!generating">
          <div class="panel-head">
            <h2>开始规划</h2>
            <p>填写你的旅行偏好，剩下交给我们</p>
          </div>

          <a-form layout="vertical" :model="form" @finish="onSubmit" class="form">
            <a-form-item label="目的地城市" name="city" :rules="[{ required: true, message: '请输入目的地城市' }]">
              <a-auto-complete
                v-model:value="form.city"
                :options="cityOptions"
                placeholder="例如：青岛、成都、大理…"
                style="width: 100%"
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
                  @click="form.city = c"
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
              <a-form-item label="旅行天数" name="travel_days" style="width: 130px">
                <a-input-number v-model:value="form.travel_days" :min="1" :max="30" style="width: 100%" />
              </a-form-item>
            </div>

            <div class="row-2">
              <a-form-item label="交通方式" name="transportation">
                <a-select v-model:value="form.transportation" placeholder="选择大交通方式">
                  <a-select-option v-for="t in transportationOptions" :key="t" :value="t">{{ t }}</a-select-option>
                </a-select>
              </a-form-item>
              <a-form-item label="住宿偏好" name="accommodation">
                <a-select v-model:value="form.accommodation" placeholder="选择住宿类型">
                  <a-select-option v-for="a in accommodationOptions" :key="a" :value="a">{{ a }}</a-select-option>
                </a-select>
              </a-form-item>
            </div>

            <a-form-item label="旅行偏好" name="preferences">
              <a-select
                v-model:value="form.preferences"
                mode="multiple"
                placeholder="可多选，决定景点搜索方向"
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
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import dayjs, { type Dayjs } from 'dayjs'
import { streamTripPlan } from '../services/api'
import { tripStore } from '../store'
import type { TripRequest, StreamEvent } from '../types'

const router = useRouter()

const hotCities = ['北京', '上海', '成都', '杭州', '西安', '青岛', '厦门', '大理']
const cityOptions = ['北京', '上海', '广州', '深圳', '成都', '杭州', '重庆', '西安', '南京', '武汉', '长沙', '厦门', '青岛', '大连', '三亚', '昆明', '丽江', '大理', '苏州', '桂林', '黄山', '天津', '哈尔滨', '乌鲁木齐'].map((v) => ({ value: v }))
const transportationOptions = ['公共交通', '自驾', '包车', '骑行', '高铁', '飞机']
const accommodationOptions = ['经济型酒店', '舒适型酒店', '豪华酒店', '民宿', '青年旅舍']
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

// ------- 进度状态（由后端 SSE 流事件驱动，替代原来的定时假推进） -------
// 图节点 → 4 步 UI 映射
const steps = [
  { icon: '🔍', label: '搜索景点', nodes: ['attraction_tool_node', 'attraction_enrich_node', 'rag_info_node'] },
  { icon: '🌤️', label: '查询天气', nodes: ['weather_tool_node'] },
  { icon: '🏨', label: '推荐酒店', nodes: ['hotel_tool_node', 'hotel_enrich_node'] },
  { icon: '📋', label: '生成计划', nodes: ['plan_node'] },
]

// 节点完成里程碑 → 进度百分比（图是并行 + 补搜循环，用"里程碑权重"近似）
const nodeMilestones: { node: string; pct: number }[] = [
  { node: 'attraction_tool_node', pct: 10 },
  { node: 'rag_info_node', pct: 25 },
  { node: 'weather_tool_node', pct: 35 },
  { node: 'attraction_enrich_node', pct: 50 },
  { node: 'hotel_tool_node', pct: 65 },
  { node: 'hotel_enrich_node', pct: 78 },
  { node: 'plan_node', pct: 90 },
]

// 节点实时状态文案
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
      // 该节点所属步骤是否全部完成
      steps.forEach((s, i) => {
        if (s.nodes.includes(ev.node) && s.nodes.every((n) => nodeDone.has(n))) {
          progress.stepDone[i] = true
        }
      })
      // 里程碑推进百分比
      for (const m of nodeMilestones) {
        if (m.node === ev.node) progress.percent = m.pct
      }
      break
    }
    case 'node_error':
      pushLog('warn', `${nodeLabels[ev.node] || ev.node} 出错，正在重试…`)
      break
    case 'done':
      break // 在 onSubmit 中统一处理
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
      if (cancelled.value) return // 用户已取消，忽略后续事件
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
        // 稍作停留展示 100% 后再跳转
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
  min-height: 100vh;
  overflow: hidden;
  background:
    radial-gradient(1200px 600px at 85% -10%, rgba(199, 91, 156, 0.45), transparent 60%),
    radial-gradient(900px 500px at -10% 30%, rgba(74, 45, 107, 0.55), transparent 55%),
    linear-gradient(135deg, #151a3d 0%, #221c4d 40%, #3b2458 75%, #5a2a52 100%);
  color: #fff;
}

/* 漂浮装饰球 */
.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(70px);
  opacity: 0.5;
  animation: float 9s ease-in-out infinite;
}
.blob-1 { width: 380px; height: 380px; background: #c75b9c; top: -80px; right: 6%; }
.blob-2 { width: 300px; height: 300px; background: #f29a4e; bottom: -90px; left: 8%; animation-delay: -3s; }
.blob-3 { width: 220px; height: 220px; background: #43c6ac; top: 45%; left: 45%; opacity: 0.3; animation-delay: -6s; }
@keyframes float {
  0%, 100% { transform: translateY(0) translateX(0); }
  50% { transform: translateY(-30px) translateX(20px); }
}

/* 星空点缀 */
.stars {
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(2px 2px at 20% 30%, rgba(255,255,255,0.7), transparent),
    radial-gradient(2px 2px at 70% 20%, rgba(255,255,255,0.5), transparent),
    radial-gradient(1.5px 1.5px at 40% 70%, rgba(255,255,255,0.6), transparent),
    radial-gradient(1.5px 1.5px at 85% 60%, rgba(255,255,255,0.4), transparent);
  pointer-events: none;
}

.home-inner {
  position: relative;
  z-index: 1;
  max-width: 1200px;
  margin: 0 auto;
  padding: 56px 40px;
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 56px;
  align-items: center;
  min-height: 100vh;
}

/* 品牌区 */
.brand-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.08);
  font-size: 13px;
  letter-spacing: 0.5px;
}
.brand-badge .dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #43f0c5;
  box-shadow: 0 0 10px #43f0c5;
}

.brand-title {
  margin-top: 22px;
  font-size: 52px;
  line-height: 1.18;
  font-weight: 800;
  letter-spacing: 1px;
}
.brand-sub {
  margin-top: 18px;
  color: rgba(255, 255, 255, 0.75);
  line-height: 1.8;
  font-size: 16px;
  max-width: 460px;
}

.features {
  margin-top: 34px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.features li {
  display: flex;
  gap: 14px;
  align-items: center;
}
.feat-ic {
  width: 46px; height: 46px;
  display: grid; place-items: center;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.16);
  font-size: 20px;
  flex-shrink: 0;
}
.features b { display: block; font-size: 15px; }
.features small { color: rgba(255, 255, 255, 0.6); font-size: 13px; }

/* 表单面板 */
.panel {
  padding: 34px 32px;
  color: #fff;
  animation: fadeUp 0.6s ease both;
}
.panel-head h2 { font-size: 24px; font-weight: 700; }
.panel-head p { color: rgba(255, 255, 255, 0.65); font-size: 13px; margin-top: 4px; }
.panel-head { margin-bottom: 22px; }

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
.form :deep(.ant-picker-suffix) { color: rgba(255, 255, 255, 0.5); }

.row-2 { display: flex; gap: 14px; }

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
.progress-view {
  text-align: center;
  padding: 18px 8px;
}
.progress-icon {
  font-size: 52px;
  display: inline-block;
}
.progress-title { margin-top: 14px; font-size: 22px; }
.progress-hint { color: rgba(255, 255, 255, 0.6); font-size: 13px; margin-top: 6px; }

.steps {
  margin: 26px 0 18px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.step {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  opacity: 0.45;
  transition: all 0.3s;
}
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
.step.active .step-ic {
  border-color: var(--gold);
  box-shadow: 0 0 16px rgba(255, 183, 3, 0.6);
}
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
.log-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: rgba(255, 255, 255, 0.35);
  flex-shrink: 0;
}
.log-line.warn .log-dot { background: #ffb703; }
.log-line.success .log-dot { background: #43f0c5; }
.progress-actions :deep(.ant-btn) { color: rgba(255, 255, 255, 0.6); }

@media (max-width: 960px) {
  .home-inner { grid-template-columns: 1fr; padding: 32px 20px; gap: 28px; }
  .brand-title { font-size: 38px; }
  .brand { text-align: center; }
  .brand-sub { margin: 14px auto 0; }
  .features { align-items: center; }
}
</style>
