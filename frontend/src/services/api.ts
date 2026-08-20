import axios from 'axios'
import type { TripRequest, TripPlanResponse, StreamEvent } from '../types'

const http = axios.create({
  baseURL: '/api',
  // Agent 真实调用可能长达 5 分钟，超时宁长勿短
  timeout: 600000,
})

/** 生成旅行计划（一次性返回完整计划，作为流式接口的兜底） */
export async function generateTripPlan(req: TripRequest, signal?: AbortSignal): Promise<TripPlanResponse> {
  const { data } = await http.post<TripPlanResponse>('/trip/plan', req, { signal })
  return data
}

/**
 * 流式生成旅行计划：消费后端 SSE 流，逐条产出实时进度事件。
 * 流式连接只按"空闲"计时，后端每 10s 有心跳 ping，不会因总时长超时断开。
 */
export async function* streamTripPlan(req: TripRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const res = await fetch('/api/trip/plan/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  })
  if (!res.ok) throw new Error(`请求失败: ${res.status} ${res.statusText}`)
  if (!res.body) throw new Error('当前浏览器不支持流式读取')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const frames = buf.split('\n\n')
      buf = frames.pop() ?? '' // 末尾可能是不完整帧，留待下次拼接
      for (const frame of frames) {
        const line = frame.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        const text = line.slice(5).trim()
        if (!text) continue
        const ev = JSON.parse(text) as StreamEvent
        yield ev
        if (ev.type === 'done') return
      }
    }
  } finally {
    reader.releaseLock()
  }
}
