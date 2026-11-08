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
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data?: TripPlan | null
}

/** SSE 流式事件（与后端 travel_plan_agent.stream_events 协议一致） */
export type StreamEvent =
  | { type: 'node_start'; node: string; label: string }
  | { type: 'node_end'; node: string; payload: Record<string, unknown> }
  | { type: 'node_error'; node: string; message: string; retry?: boolean }
  | { type: 'done'; success: boolean; message: string; data?: TripPlan | null }

export interface TripRequest {
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
  /** 匿名会话 ID，用于召回该会话上传的知识库内容 */
  session_id?: string
}

/** 从对话 / 首页跳转到快速开始时的预填表单（字段均可选） */
export interface TripPrefill {
  city?: string
  start_date?: string
  end_date?: string
  travel_days?: number
  transportation?: string
  accommodation?: string
  preferences?: string[]
  free_text_input?: string
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
}

/** POST /api/chat/stream 的请求体（后端后续按此实现） */
export interface ChatRequest {
  session_id?: string
  message: string
  city?: string
}

/**
 * 对话 SSE 事件（后端后续按此实现）：
 * data: {"type":"token","delta":"..."}
 * data: {"type":"done","session_id":"..."}
 * data: {"type":"error","message":"..."}
 */
export type ChatStreamEvent =
  | { type: 'token'; delta: string }
  | { type: 'done'; message?: string; session_id?: string }
  | { type: 'error'; message: string }

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
