import axios from 'axios'
import type {
  ChatRequest,
  ChatStreamEvent,
  KnowledgeConfigResponse,
  KnowledgeListResponse,
  KnowledgeUploadResponse,
  ServerSession,
  SessionResponse,
  StreamEvent,
  TrainSearchResponse,
  TripPlanResponse,
  TripRequest,
} from '../types'

const API_BASE = '/api/v1'

const http = axios.create({
  baseURL: API_BASE,
  // Agent 真实调用可能长达 5 分钟，超时宁长勿短
  timeout: 600000,
})

/** 生成旅行计划（一次性返回完整计划，作为流式接口的兜底） */
export async function generateTripPlan(req: TripRequest, signal?: AbortSignal): Promise<TripPlanResponse> {
  const { data } = await http.post<TripPlanResponse>('/trip/plan', req, { signal })
  return data
}

/** 查询 12306 实时车次（结果页票面轮播使用）。 */
export async function searchTrainTickets(
  params: { fromCity: string; toCity: string; date: string; filterFlags?: string },
  signal?: AbortSignal,
): Promise<TrainSearchResponse> {
  const { data } = await http.get<TrainSearchResponse>('/trip/trains', {
    params: {
      from_city: params.fromCity,
      to_city: params.toCity,
      date: params.date,
      filter_flags: params.filterFlags ?? '',
    },
    signal,
  })
  return data
}

/* ---------------- 会话 ---------------- */

/** 校验 user_id + session_id；会话不存在时由后端新建并返回。 */
export async function ensureSession(
  userId: string,
  sessionId?: string | null,
  title = '',
  city = '',
  signal?: AbortSignal,
): Promise<ServerSession> {
  const { data } = await http.post<SessionResponse>(
    '/sessions/ensure',
    { user_id: userId, session_id: sessionId || null, title, city },
    { signal },
  )
  return data.session
}

export async function createSession(
  userId: string,
  title = '',
  city = '',
): Promise<ServerSession> {
  const { data } = await http.post<SessionResponse>('/sessions', {
    user_id: userId,
    title,
    city,
  })
  return data.session
}

export async function listSessions(userId: string): Promise<ServerSession[]> {
  const { data } = await http.get<{ success: boolean; sessions: ServerSession[] }>('/sessions', {
    params: { user_id: userId },
  })
  return data.sessions
}

export async function getSession(sessionId: string, userId: string): Promise<ServerSession> {
  const { data } = await http.get<SessionResponse>(
    `/sessions/${encodeURIComponent(sessionId)}`,
    { params: { user_id: userId } },
  )
  return data.session
}

export async function deleteSession(sessionId: string, userId: string): Promise<void> {
  await http.delete(`/sessions/${encodeURIComponent(sessionId)}`, {
    params: { user_id: userId },
  })
}

/* ---------------- 知识库上传 ---------------- */

/** 上传文件/文本到当前用户的知识库。不要手动设置 Content-Type，交给浏览器生成 boundary。 */
export async function uploadKnowledge(
  formData: FormData,
  signal?: AbortSignal,
): Promise<KnowledgeUploadResponse> {
  const { data } = await http.post<KnowledgeUploadResponse>('/knowledge/upload', formData, {
    signal,
  })
  return data
}

/** 读取后端生效的上传上限（文件大小 / 文本长度）。 */
export async function getKnowledgeConfig(signal?: AbortSignal): Promise<KnowledgeConfigResponse> {
  const { data } = await http.get<KnowledgeConfigResponse>('/knowledge/config', { signal })
  return data
}

/** 列出当前用户已上传的文档（只返回预览）。 */
export async function listKnowledge(
  userId: string,
  signal?: AbortSignal,
): Promise<KnowledgeListResponse> {
  const { data } = await http.get<KnowledgeListResponse>('/knowledge/list', {
    params: { user_id: userId },
    signal,
  })
  return data
}

/** 删除当前用户自己上传的文档。 */
export async function deleteKnowledge(docId: string, userId: string): Promise<void> {
  await http.delete(`/knowledge/${encodeURIComponent(docId)}`, {
    params: { user_id: userId },
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
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    let message = `请求失败: ${res.status} ${res.statusText}`
    try {
      const payload = await res.json()
      message = payload?.message || payload?.detail || message
    } catch {
      /* 非 JSON 错误响应 */
    }
    throw new Error(message)
  }
  if (!res.body) throw new Error('当前浏览器不支持流式读取')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      // sse-starlette 使用 CRLF 分帧；统一成 LF 后再按空行切帧
      buf = (buf + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n')
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
  return streamSSE<StreamEvent>(`${API_BASE}/trip/plan/stream`, req, signal)
}

/**
 * AI 对话流式接口：后端持久化会话与消息，并通过 SSE 返回 token / done / error。
 */
export function streamChat(req: ChatRequest, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
  return streamSSE<ChatStreamEvent>(`${API_BASE}/chat/stream`, req, signal)
}

/** 断线续传：补发已生成但客户端未收到的 token。 */
export function resumeChat(
  params: { userId: string; sessionId: string; offset: number },
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  return streamSSE<ChatStreamEvent>(
    `${API_BASE}/chat/resume`,
    { user_id: params.userId, session_id: params.sessionId, offset: params.offset },
    signal,
  )
}

/** 取消正在后台生成的对话回复。 */
export async function cancelChat(params: { userId: string; sessionId: string }): Promise<void> {
  await http.post('/chat/cancel', {
    user_id: params.userId,
    session_id: params.sessionId,
  })
}

/** 断线续传：按 record_id 补发未收到的行程节点事件。 */
export function resumeTripPlan(
  params: { recordId: string; userId: string; after: number },
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  return streamSSE<StreamEvent>(
    `${API_BASE}/trip/plan/resume`,
    { record_id: params.recordId, user_id: params.userId, after: params.after },
    signal,
  )
}

/** 取消正在后台执行的行程规划。 */
export async function cancelTripPlan(params: { recordId: string; userId: string }): Promise<void> {
  await http.post('/trip/plan/cancel', {
    record_id: params.recordId,
    user_id: params.userId,
  })
}
