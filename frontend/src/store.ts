import { reactive, watch } from 'vue'
import type {
  ChatMessage,
  ChatSession,
  ServerMessage,
  ServerSession,
  TripPlan,
  TripPrefill,
} from './types'

/** 跨页面共享的轻量状态（快速开始生成后写入，Result 读取展示） */
export const tripStore = reactive<{
  plan: TripPlan | null
  loading: boolean
  /** 其他入口（对话页 / 首页城市链接）带到快速开始的预填，消费后置空 */
  prefill: TripPrefill | null
}>({
  plan: null,
  loading: false,
  prefill: null,
})

/**
 * AI 对话状态：会话与消息以服务端 PostgreSQL 为准，
 * 这里只是当前页面的内存缓存；localStorage 仅保存 activeId。
 */
export const chatStore = reactive<{
  sessions: ChatSession[]
  activeId: string | null
  messages: ChatMessage[]
  streaming: boolean
  loading: boolean
}>({
  sessions: [],
  activeId: null,
  messages: [],
  streaming: false,
  loading: false,
})

const ACTIVE_SESSION_KEY = 'lvji_active_session'

try {
  chatStore.activeId = localStorage.getItem(ACTIVE_SESSION_KEY)
} catch {
  /* 隐私模式/禁用 localStorage 时忽略 */
}

watch(
  () => chatStore.activeId,
  (id) => {
    try {
      if (id) localStorage.setItem(ACTIVE_SESSION_KEY, id)
      else localStorage.removeItem(ACTIVE_SESSION_KEY)
    } catch {
      /* ignore */
    }
  },
)

/**
 * 匿名用户 ID：不做登录时，用它作为知识库 metadata 的 owner_id。
 * 持久化在 localStorage，刷新后仍能访问自己上传的资料。
 */
const CLIENT_ID_KEY = 'lvji_client_id'

function createClientId(): string {
  const cryptoObj = globalThis.crypto as Crypto | undefined
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
    return cryptoObj.randomUUID()
  }
  return `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}

let userId = ''
try {
  userId = localStorage.getItem(CLIENT_ID_KEY) || ''
} catch {
  /* 隐私模式/禁用 localStorage 时退化为内存 ID */
}

if (!userId) {
  userId = createClientId()
  try {
    localStorage.setItem(CLIENT_ID_KEY, userId)
  } catch {
    /* ignore */
  }
}

export function getUserId(): string {
  return userId
}

export function toChatMessage(message: ServerMessage): ChatMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    createdAt: Date.parse(message.created_at) || Date.now(),
    status: message.status || 'done',
  }
}

export function toChatSession(session: ServerSession): ChatSession {
  return {
    id: session.id,
    title: session.title,
    city: session.city,
    messages: Array.isArray(session.messages)
      ? session.messages.map(toChatMessage)
      : [],
    createdAt: Date.parse(session.created_at) || Date.now(),
    updatedAt: Date.parse(session.updated_at) || Date.now(),
  }
}
