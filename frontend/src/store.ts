import { reactive, watch } from 'vue'
import type { ChatSession, TripPlan, TripPrefill } from './types'

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

/** AI 对话状态：模块级 reactive；下面是 sessions/activeId 的本地持久化。 */
export const chatStore = reactive<{
  sessions: ChatSession[]
  activeId: string | null
  streaming: boolean
}>({
  sessions: [],
  activeId: null,
  streaming: false,
})

/**
 * 会话持久化：刷新后保留 activeId，知识库上传才能继续按同一个会话 ID 检索。
 * 只保存 sessions/activeId，streaming 这种瞬时状态不落盘。
 */
const CHAT_STORE_KEY = 'lvji_chat_store'
const MAX_SESSIONS = 30

try {
  const raw = localStorage.getItem(CHAT_STORE_KEY)
  if (raw) {
    const saved = JSON.parse(raw) as { sessions?: ChatSession[]; activeId?: string | null }
    if (Array.isArray(saved.sessions)) {
      chatStore.sessions = saved.sessions
        .filter((session) => session && typeof session.id === 'string')
        .map((session) => ({
          ...session,
          messages: Array.isArray(session.messages) ? session.messages : [],
          title: typeof session.title === 'string' ? session.title : '',
          createdAt: typeof session.createdAt === 'number' ? session.createdAt : Date.now(),
          updatedAt: typeof session.updatedAt === 'number' ? session.updatedAt : Date.now(),
        }))
        .slice(0, MAX_SESSIONS)
      chatStore.activeId =
        typeof saved.activeId === 'string' &&
        chatStore.sessions.some((session) => session.id === saved.activeId)
          ? saved.activeId
          : (chatStore.sessions[0]?.id ?? null)
      // 页面在流式中被关闭时，恢复后的消息不应一直显示“正在输入”。
      for (const session of chatStore.sessions) {
        if (!Array.isArray(session.messages)) continue
        for (const chatMessage of session.messages) {
          if (chatMessage.status === 'streaming') chatMessage.status = 'stopped'
        }
      }
    }
  }
} catch {
  /* 隐私模式/坏数据时忽略 */
}

let saveTimer: number | undefined
watch(
  () => [chatStore.sessions, chatStore.activeId] as const,
  () => {
    if (saveTimer) window.clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => {
      try {
        localStorage.setItem(
          CHAT_STORE_KEY,
          JSON.stringify({ sessions: chatStore.sessions, activeId: chatStore.activeId }),
        )
      } catch {
        /* 配额满时忽略 */
      }
    }, 300)
  },
  { deep: true },
)

/**
 * 匿名会话 ID：不做登录时，用它作为向量库 metadata 的 owner_id。
 * 本轮先持久化在 localStorage，刷新后仍能访问自己上传的资料。
 */
const CLIENT_ID_KEY = 'lvji_client_id'

function createClientId(): string {
  const cryptoObj = globalThis.crypto as Crypto | undefined
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
    return cryptoObj.randomUUID()
  }
  return `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}

let clientId = ''
try {
  clientId = localStorage.getItem(CLIENT_ID_KEY) || ''
} catch {
  /* 隐私模式/禁用 localStorage 时退化为内存 ID */
}

if (!clientId) {
  clientId = createClientId()
  try {
    localStorage.setItem(CLIENT_ID_KEY, clientId)
  } catch {
    /* ignore */
  }
}

/**
 * 知识库/规划使用的固定匿名 ID。
 *
 * 不再绑定 chatStore.activeId：聊天会话刷新后可能重建，会导致刚上传的
 * 知识库“消失”。这里使用 localStorage 里的浏览器级 ID，刷新、切换对话都不变。
 * 需要按对话隔离时，可以改回 chatStore.activeId，但要同时持久化会话列表。
 */
export function getSessionId(): string {
  return clientId
}
