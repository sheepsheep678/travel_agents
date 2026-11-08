/**
 * 本地 mock 对话流。
 *
 * 后端 /api/chat/stream 尚未实现，这里用关键词规则生成一段回复并按字符分片
 * 产出 ChatStreamEvent，供前端完整演示流式效果。后端就绪后把 MOCK_CHAT 置为
 * false（services/api.ts 自动改走真实 SSE）。
 *
 * 回复只给规划思路与操作建议，不伪造具体地址 / 价格，符合项目防幻觉原则。
 */
import { sketchbookCities } from '../data/sketchbookCities'
import type { ChatRequest, ChatStreamEvent } from '../types'

export const MOCK_CHAT = true

const CITY_NAMES = sketchbookCities.map((c) => c.name)

const CN_NUM: Record<string, number> = {
  一: 1, 两: 2, 二: 2, 三: 3, 四: 4, 五: 5,
  六: 6, 七: 7, 八: 8, 九: 9, 十: 10,
}

function findCity(text: string): string | null {
  return CITY_NAMES.find((n) => text.includes(n)) ?? null
}

function extractDays(text: string): number | null {
  const m = text.match(/(\d+|[一二两三四五六七八九十])\s*(?:天|日)/)
  if (!m) return null
  return /^\d+$/.test(m[1]) ? Number(m[1]) : CN_NUM[m[1]] ?? null
}

function buildReply(message: string): string {
  const city = findCity(message)
  const days = extractDays(message)
  const tripName = city ? `${city}${days ? ` ${days} 天` : ''}的行程` : '这趟行程'

  if (/你好|您好|hi|hello|在吗/i.test(message)) {
    return `你好，我是旅迹智绘的旅行助手。

你可以直接告诉我：想去哪座城市、大概几天、和谁一起、更在意什么。我会先帮你把行程节奏和取舍理清楚；如果你已经想好了，也可以点「用表单生成完整行程」，让行程助手结合真实的地点、酒店和天气信息，直接生成一版。`
  }

  if (/亲子|孩子|带娃|小朋友/.test(message)) {
    return `${tripName}如果带着孩子，节奏要比常规行程松一半：

每天安排 1 个主景点 + 1 个可以随时退出的备选，午后留出回酒店休息的时间。住宿优先选地铁沿线、含早餐的酒店，餐饮避开排长队的网红店会更省心。

点「用表单生成完整行程」时，把孩子的年龄写进额外要求，生成时会按更宽松的节奏安排，避免每天走太多路。`
  }

  if (/父母|老人|长辈|爸妈/.test(message)) {
    return `带父母出行，重点不是打卡数量，而是少走路、少换乘、随时有地方坐。

建议每天只排一个核心景点，酒店选在景区或地铁站步行 10 分钟内；台阶多、坡道多的景点放在天气好的上午。

在「快速开始」的额外要求里写一句「同行有老人，节奏慢、少步行」，生成时会按更慢的节奏来安排。`
  }

  if (/美食|好吃|吃|餐厅|小吃/.test(message)) {
    return `找吃的可以先按「一顿本地菜 + 一顿小吃 + 一顿机动」来配，别为了网红店把路线拉得太散。

早餐在老城区找现做的本地早点，午餐跟着当天景点走，晚餐再专门去一条美食街或商圈。具体店名建议到当地用地图看实时评分和排队情况，而不是照搬攻略。

把「美食」选进偏好后生成行程，餐饮会尽量安排在景点附近，减少来回折返。`
  }

  if (/雨|天气|下雨|台风|降温/.test(message)) {
    return `遇到雨天，把行程拆成「室内主线 + 天气窗口机动」：

上午安排博物馆、美术馆或商场，雨小的时候再去户外景点，晚上把步行街换成有顶棚的街区。生成时会参考当天的天气，把室内备选写进计划，但临近出发仍建议再看一次预报。

如果日期已经确定，直接去「快速开始」生成一版，再按雨天备选微调景点顺序就好。`
  }

  if (/预算|省钱|便宜|花费|多少钱/.test(message)) {
    return `控制预算最有效的三件事：住地铁沿线而不是景区门口、只买真正想去的门票、把长距离移动集中在同一天。

生成的计划会按门票 / 酒店 / 餐饮 / 交通分项列出预算，方便看出哪一项偏高，再决定是换住宿档次还是减少收费景点。

先定城市和天数，就能拿到一版可以横向对比的估算。`
  }

  if (/交通|住宿|酒店|住哪|怎么去/.test(message)) {
    return `交通和住宿最好一起定：先确定每天的主要活动区域，再选离地铁 10 分钟内的酒店，最后决定要不要包车。

城市内短途用地铁 + 步行通常最稳；去郊区长线（比如长城、海岛）再考虑包车或一日游。

告诉我城市和天数，我可以先帮你把住宿区域的大方向定下来，具体酒店会在生成时按景点位置推荐。`
  }

  if (/几天|几日|行程|规划|安排|怎么玩|路线|攻略/.test(message)) {
    return `${tripName}可以先按「每天 2–3 个景点」来排：

第一天放在城市核心区，景点之间尽量步行可达；第二天拉远一点，安排一个需要半天的重点；第三天留给博物馆、老街或机动调整。

确认出行日期、交通方式和住宿档次后，点「用表单生成完整行程」——行程助手会结合真实地点、周边酒店和天气信息，把框架变成具体路线，并再检查一遍每天的时长和路线衔接。`
  }

  return `可以，我先帮你把问题拆小一点：

1. 想去哪座城市？目前支持北京、上海、广州、杭州、西安、成都、重庆、长沙、青岛、厦门、南京。
2. 大概几天、什么日期出发？
3. 更在意什么——历史文化、自然风光、美食，还是带孩子 / 父母同行？

有了这三点，我可以先给一个行程框架；想直接拿到带真实地点、酒店和天气的完整计划，也可以随时点「用表单生成完整行程」。`
}

function abortError(): DOMException {
  return new DOMException('Aborted', 'AbortError')
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError())
      return
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    function onAbort() {
      window.clearTimeout(timer)
      reject(abortError())
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/** 按 2–4 个字符切分，模拟 token 流 */
function splitChunks(text: string): string[] {
  const chars = Array.from(text)
  const chunks: string[] = []
  let i = 0
  while (i < chars.length) {
    const n = 2 + Math.floor(Math.random() * 3)
    chunks.push(chars.slice(i, i + n).join(''))
    i += n
  }
  return chunks
}

export async function* streamChatMock(
  req: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const full = buildReply(req.message)
  for (const chunk of splitChunks(full)) {
    await delay(22 + Math.random() * 18, signal)
    yield { type: 'token', delta: chunk }
  }
  yield { type: 'done', session_id: req.session_id }
}
