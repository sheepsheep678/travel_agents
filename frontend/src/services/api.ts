import axios from 'axios'
import type {
  ChatRequest,
  ChatStreamEvent,
  KnowledgeListResponse,
  KnowledgeUploadResponse,
  StreamEvent,
  TripPlanResponse,
  TripRequest,
} from '../types'
import { MOCK_CHAT, streamChatMock } from './chatMock'

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

/* ---------------- 知识库上传 ---------------- */

/** 上传文件/文本到当前会话的知识库。不要手动设置 Content-Type，交给浏览器生成 boundary。 */
export async function uploadKnowledge(
  formData: FormData,
  signal?: AbortSignal,
): Promise<KnowledgeUploadResponse> {
  const { data } = await http.post<KnowledgeUploadResponse>('/knowledge/upload', formData, {
    signal,
  })
  return data
}

/** 列出当前会话已上传的文档（只返回预览）。 */
export async function listKnowledge(
  sessionId: string,
  signal?: AbortSignal,
): Promise<KnowledgeListResponse> {
  const { data } = await http.get<KnowledgeListResponse>('/knowledge/list', {
    params: { session_id: sessionId },
    signal,
  })
  return data
}

/** 删除当前会话自己上传的文档。 */
export async function deleteKnowledge(docId: string, sessionId: string): Promise<void> {
  await http.delete(`/knowledge/${encodeURIComponent(docId)}`, {
    params: { session_id: sessionId },
  })
}

/**
 * 通用 SSE 消费：POST JSON，按 `\n\n` 分帧，取 `data:` 行，忽略 `: ping` 注释帧。
 * 点击「停止」时通过 AbortSignal 中断（抛 AbortError，由调用方静默处理）。
 */
async function* streamSSE<T extends { type: string }>(
  url: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
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
        const ev = JSON.parse(text) as T
        yield ev
        if (ev.type === 'done' || ev.type === 'error') return
      }
    }
  } finally {
    reader.releaseLock()
  }
}

/**
 * 流式生成旅行计划：消费后端 SSE 流，逐条产出实时进度事件。
 * 流式连接只按"空闲"计时，后端每 10s 有心跳 ping，不会因总时长超时断开。
 */
export function streamTripPlan(req: TripRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  return streamSSE<StreamEvent>('/api/trip/plan/stream', req, signal)
}

/**
 * AI 对话流式接口。
 *
 * 后端接口约定（尚未实现）：
 *   POST /api/chat/stream
 *   body: { session_id?: string; message: string; city?: string }
 *   SSE: token / done / error（见 types/index.ts 的 ChatStreamEvent）
 *
 * 后端就绪后把 services/chatMock.ts 的 MOCK_CHAT 置为 false 即可切到真实接口。
 */
export function streamChat(req: ChatRequest, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
  if (MOCK_CHAT) return streamChatMock(req, signal)
  return streamSSE<ChatStreamEvent>('/api/chat/stream', req, signal)
}
