/** 与后端 Pydantic 模型一一对应的 TypeScript 类型 */

export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address: string
  location: Location
  visit_duration: number
  description: string
  category?: string | null
  rating?: number | null
  photos?: string[]
  poi_id?: string
  image_url?: string | null
  ticket_price?: number
}

export interface Meal {
  type: string
  name: string
  address?: string | null
  location?: Location | null
  description?: string | null
  estimated_cost?: number
}

export interface Hotel {
  name: string
  address?: string
  location?: Location | null
  price_range?: string
  rating?: string
  distance?: string
  type?: string
  estimated_cost?: number
}

export interface DayPlan {
  date: string
  day_index: number
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel | null
  attractions: Attraction[]
  meals: Meal[]
}

export interface WeatherInfo {
  date: string
  day_weather?: string
  night_weather?: string
  day_temp?: number | string
  night_temp?: number | string
  wind_direction?: string
  wind_power?: string
}

export interface Budget {
  total_attractions?: number
  total_hotels?: number
  total_meals?: number
  total_transportation?: number
  total?: number
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  budget?: Budget | null
  transport?: IntercityTransport | null
}

export interface IntercityTransport {
  from_city: string
  to_city: string
  outbound?: TrainTicket | null
  return_ticket?: TrainTicket | null
  outbound_options: TrainTicket[]
  return_options: TrainTicket[]
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data?: TripPlan | null
}

/* ---------------- 12306 车次票面 ---------------- */

export interface TrainSeatPrice {
  seat_name?: string
  short?: string
  num?: number | string | null
  price?: number | null
  discount?: number | null
}

export interface TrainTicket {
  train_no?: string
  train_code?: string
  start_date?: string
  arrive_date?: string
  start_time?: string
  arrive_time?: string
  duration?: string
  from_station?: string
  to_station?: string
  from_station_telecode?: string
  to_station_telecode?: string
  prices?: TrainSeatPrice[]
  flags?: string[]
  /** 行程上下文中的方向：outbound / return */
  direction?: string
}

export interface TrainSearchResponse {
  success: boolean
  message?: string
  from_city?: string
  to_city?: string
  date?: string
  tickets: TrainTicket[]
}

/** SSE 流式事件（与后端 travel_plan_agent.stream_events 协议一致） */
export type StreamEvent =
  | { type: 'meta'; record_id: string; seq?: number }
  | { type: 'node_start'; node: string; label: string; seq?: number }
  | { type: 'node_end'; node: string; payload: Record<string, unknown>; seq?: number }
  | { type: 'node_error'; node: string; message: string; retry?: boolean; seq?: number }
  | { type: 'done'; success: boolean; message: string; data?: TripPlan | null; seq?: number }

export interface TripRequest {
  city: string
  /** 出发城市，用于查询跨城高铁；留空则不查 */
  origin_city?: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
  /** 浏览器匿名用户 ID，用于召回该用户上传的知识库内容 */
  user_id?: string
  /** 服务端会话 ID，用于校验归属并作为 Agent checkpoint 的 thread_id */
  session_id?: string
}

/** 从对话 / 首页跳转到快速开始时的预填表单（字段均可选） */
export interface TripPrefill {
  city?: string
  origin_city?: string
  start_date?: string
  end_date?: string
  travel_days?: number
  transportation?: string
  accommodation?: string
  preferences?: string[]
  free_text_input?: string
  user_id?: string
  session_id?: string
}

/* ---------------- AI 对话 ---------------- */

export type ChatRole = 'user' | 'assistant'
export type ChatMessageStatus = 'streaming' | 'done' | 'stopped' | 'error'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  createdAt: number
  status: ChatMessageStatus
  error?: string
}

export interface ChatSession {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: number
  updatedAt: number
  city?: string
}

/** POST /api/v1/chat/stream 的请求体 */
export interface ChatRequest {
  user_id: string
  session_id: string
  message: string
  city?: string
  /** 重新生成：后端不会重复写入用户消息，并删除最后一条助手回复 */
  regenerate?: boolean
}

/**
 * 对话 SSE 事件：
 * data: {"type":"token","delta":"..."}
 * data: {"type":"done","session_id":"..."}
 * data: {"type":"error","message":"..."}
 */
export type ChatStreamEvent =
  | { type: 'token'; delta: string }
  | { type: 'done'; message?: string; session_id?: string }
  | { type: 'error'; message: string }

/* ---------------- 服务端会话 ---------------- */

export interface ServerMessage {
  id: string
  role: ChatRole
  content: string
  created_at: string
  status: ChatMessageStatus
}

export interface ServerSession {
  id: string
  user_id: string
  title: string
  city: string
  created_at: string
  updated_at: string
  messages: ServerMessage[]
}

export interface SessionResponse {
  success: boolean
  session: ServerSession
}

export interface SessionListResponse {
  success: boolean
  sessions: ServerSession[]
}

export interface SessionDeleteResponse {
  success: boolean
  message: string
}

/* ---------------- 知识库上传 ---------------- */

export type KnowledgeSourceType = 'md' | 'txt' | 'pdf' | 'image'

export interface KnowledgeItem {
  doc_id: string
  title: string
  preview: string
  source_type: KnowledgeSourceType | string
  chunk_count: number
  city?: string
  source?: string
  created_at: string
  scope?: string
}

export interface KnowledgeUploadResponse {
  success: boolean
  message: string
  item?: KnowledgeItem
}

export interface KnowledgeListResponse {
  success: boolean
  items: KnowledgeItem[]
}

export interface KnowledgeConfigResponse {
  success: boolean
  max_file_mb: number
  max_text_chars: number
}
