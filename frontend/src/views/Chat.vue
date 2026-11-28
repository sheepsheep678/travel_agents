<template>
  <div class="site-page chat-page">
    <SiteHeader active="chat" />

    <div class="chat-body">
      <ChatSidebar
        :sessions="chatStore.sessions"
        :active-id="chatStore.activeId"
        :open="sidebarOpen"
        @new="newSession"
        @select="selectSession"
        @remove="removeSession"
        @close="sidebarOpen = false"
      />

      <main class="chat-main">
        <div class="chat-toolbar">
          <button
            class="chat-menu-btn"
            aria-label="打开会话列表"
            aria-controls="chat-sidebar"
            :aria-expanded="sidebarOpen"
            @click="sidebarOpen = true"
          >
            ☰
          </button>
          <span class="chat-title">{{ activeSession?.title || '新的对话' }}</span>
          <button class="chat-kb-btn" @click="openKnowledge">＋ 知识库</button>
        </div>

        <div ref="scrollEl" class="chat-scroll" @scroll.passive="onScroll">
          <div class="chat-thread">
            <div v-if="isEmpty" class="chat-empty">
              <SealMark size="lg" />
              <h1 class="chat-empty-title">今天想去哪里？</h1>
              <p class="chat-empty-sub">告诉我城市、天数和同行的人，我们先聊聊这趟旅行怎么安排。</p>
              <div class="chat-suggestions">
                <button
                  v-for="q in SUGGESTIONS"
                  :key="q"
                  class="chat-suggestion"
                  @click="send(q)"
                >
                  {{ q }}
                </button>
              </div>
            </div>

            <ChatMessageItem
              v-for="m in messages"
              :key="m.id"
              :message="m"
              :can-regenerate="m.role === 'assistant' && m.id === lastAssistantId() && m.status === 'done'"
              :can-plan="hasUserMessage && m.id === lastAssistantId() && m.status === 'done'"
              :plan-loading="planLoading"
              @regenerate="regenerate"
              @go-plan="goPlan"
            />
          </div>
        </div>

        <button v-if="showJump" class="chat-jump" @click="jumpToBottom">↓ 回到底部</button>

        <div class="chat-composer-shell">
          <ChatComposer :streaming="chatStore.streaming" @send="send" @stop="stop" />
        </div>
      </main>
    </div>

    <KnowledgeDrawer
      :open="knowledgeOpen"
      :user-id="userId"
      @close="knowledgeOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import SiteHeader from '../components/site/SiteHeader.vue'
import SealMark from '../components/site/SealMark.vue'
import ChatSidebar from '../components/chat/ChatSidebar.vue'
import ChatMessageItem from '../components/chat/ChatMessageItem.vue'
import ChatComposer from '../components/chat/ChatComposer.vue'
import KnowledgeDrawer from '../components/chat/KnowledgeDrawer.vue'
import { usePaperTheme } from '../composables/usePaperTheme'
import { chatStore, getUserId, toChatSession, tripStore } from '../store'
import {
  cancelChat,
  createSession,
  deleteSession,
  getSession,
  listSessions,
  resumeChat,
  streamChat,
  suggestTripPrefill,
} from '../services/api'
import { sketchbookCities } from '../data/sketchbookCities'
import type {
  ChatMessage,
  ChatSession,
  ChatStreamEvent,
  TripPrefill,
} from '../types'

usePaperTheme()

const router = useRouter()
const userId = getUserId()

const CITY_NAMES = sketchbookCities.map((c) => c.name)
const PREF_KEYS = [
  '历史文化', '自然风光', '美食', '休闲度假', '亲子', '购物', '夜生活',
  '博物馆', '海滩', '主题公园', '摄影', '户外徒步', '古镇', '温泉',
]

const SUGGESTIONS = [
  '帮我规划北京三日游',
  '成都适合带父母去吗？',
  '周末去杭州怎么安排？',
  '上海下雨天的备选方案',
]

const sidebarOpen = ref(false)
const knowledgeOpen = ref(false)
const scrollEl = ref<HTMLElement>()
const showJump = ref(false)
let abortCtrl: AbortController | null = null
let stickToBottom = true
// 只有用户显式点「停止」才要求后端取消；断线/离页只停止本地接收
let stopRequested = false

const activeSession = computed(
  () => chatStore.sessions.find((s) => s.id === chatStore.activeId) ?? null,
)
const messages = computed(() => chatStore.messages)
const isEmpty = computed(() => messages.value.length === 0)

const sessionCity = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const city = CITY_NAMES.find((n) => messages.value[i].content.includes(n))
    if (city) return city
  }
  return activeSession.value?.city || ''
})

const hasUserMessage = computed(() =>
  messages.value.some((m) => m.role === 'user'),
)

function errorText(e: any, fallback: string): string {
  return e?.response?.data?.message || e?.message || fallback
}

function uid(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

function lastAssistantId(): string | null {
  const list = messages.value
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].role === 'assistant') return list[i].id
  }
  return null
}

function lastUserContent(): string {
  const list = messages.value
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].role === 'user') return list[i].content
  }
  return ''
}

function stop() {
  // 停止按钮：连同后台生成一起取消
  stopRequested = true
  abortCtrl?.abort()
}

function abortStream() {
  abortCtrl?.abort()
}

function stopIfStreaming() {
  // 新建/切换会话只停止本地接收，后台生成继续；切回来可从历史获取完整回复
  if (chatStore.streaming) abortStream()
}

function openKnowledge() {
  sidebarOpen.value = false
  knowledgeOpen.value = true
}

/* ------- 服务端会话同步 ------- */

async function loadSessions() {
  chatStore.loading = true
  try {
    const list = await listSessions(userId)
    chatStore.sessions = list.map((session) => ({
      ...toChatSession(session),
      messages: [],
    }))
    if (
      chatStore.activeId &&
      !chatStore.sessions.some((session) => session.id === chatStore.activeId)
    ) {
      chatStore.activeId = null
    }
    if (!chatStore.activeId && chatStore.sessions.length) {
      chatStore.activeId = chatStore.sessions[0].id
    }
  } catch (e: any) {
    message.error(errorText(e, '会话列表加载失败'))
  } finally {
    chatStore.loading = false
  }
}

async function loadMessages(id: string) {
  try {
    const detail = await getSession(id, userId)
    const converted = toChatSession(detail)
    const index = chatStore.sessions.findIndex((session) => session.id === id)
    if (index >= 0) {
      chatStore.sessions[index] = { ...converted, messages: [] }
    }
    if (chatStore.activeId === id) {
      chatStore.messages = converted.messages
    }
  } catch (e: any) {
    message.error(errorText(e, '会话消息加载失败'))
  }
}

async function newSession() {
  stopIfStreaming()
  try {
    const session = toChatSession(await createSession(userId))
    chatStore.sessions.unshift({ ...session, messages: [] })
    chatStore.activeId = session.id
    chatStore.messages = []
    sidebarOpen.value = false
    stickToBottom = true
    await nextTick()
    scrollToBottom(true)
  } catch (e: any) {
    message.error(errorText(e, '创建会话失败'))
  }
}

async function selectSession(id: string) {
  if (id === chatStore.activeId) {
    sidebarOpen.value = false
    return
  }
  stopIfStreaming()
  chatStore.activeId = id
  chatStore.messages = []
  sidebarOpen.value = false
  stickToBottom = true
  await loadMessages(id)
  await nextTick()
  scrollToBottom(true)
}

async function removeSession(id: string) {
  if (id === chatStore.activeId) {
    stopIfStreaming()
    // 会话即将删除，后台生成已无归属，显式取消
    cancelChat({ userId, sessionId: id }).catch(() => {})
  }
  try {
    await deleteSession(id, userId)
  } catch (e: any) {
    message.error(errorText(e, '删除会话失败'))
    return
  }
  chatStore.sessions = chatStore.sessions.filter((session) => session.id !== id)
  if (chatStore.activeId === id) {
    chatStore.activeId = chatStore.sessions[0]?.id ?? null
    chatStore.messages = []
    if (!chatStore.activeId) await newSession()
    else await loadMessages(chatStore.activeId)
  }
}

async function ensureActiveSession(): Promise<ChatSession | null> {
  if (activeSession.value) return activeSession.value
  await newSession()
  return activeSession.value
}

function applyChatEvent(
  ev: ChatStreamEvent,
  msg: ChatMessage,
  session: ChatSession,
): boolean {
  if (ev.type === 'token') {
    msg.content += ev.delta
    session.updatedAt = Date.now()
    return false
  }
  if (ev.type === 'error') {
    msg.status = 'error'
    msg.error = ev.message
    return true
  }
  if (ev.session_id && ev.session_id !== session.id) {
    // 理论上不会发生；保持本地状态与服务端一致
    session.id = ev.session_id
    chatStore.activeId = ev.session_id
  }
  msg.status = 'done'
  return true
}

async function pumpChat(
  events: AsyncIterable<ChatStreamEvent>,
  msg: ChatMessage,
  session: ChatSession,
): Promise<boolean> {
  for await (const ev of events) {
    const finished = applyChatEvent(ev, msg, session)
    if (ev.type === 'token') {
      await nextTick()
      scrollToBottom()
    }
    if (finished) return true
  }
  return false
}

function settleAborted(msg: ChatMessage) {
  if (!msg.content) {
    const i = chatStore.messages.findIndex((m) => m.id === msg.id)
    if (i >= 0) chatStore.messages.splice(i, 1)
  } else {
    msg.status = 'stopped'
  }
}

function handleAbort(msg: ChatMessage, session: ChatSession) {
  // 显式停止才取消后台；网络断开、刷新、路由卸载时让生成继续，重连可续传
  if (stopRequested) {
    cancelChat({ userId, sessionId: session.id }).catch(() => {})
  }
  stopRequested = false
  settleAborted(msg)
}

async function runAssistant(
  session: ChatSession,
  userText: string,
  regenerate = false,
) {
  chatStore.messages.push({
    id: uid('m'),
    role: 'assistant',
    content: '',
    createdAt: Date.now(),
    status: 'streaming',
  })
  // 必须拿 reactive 数组里的代理对象；直接改 push 进去的原始对象不会触发视图更新
  const msg = chatStore.messages[chatStore.messages.length - 1]
  session.updatedAt = Date.now()
  chatStore.streaming = true
  stopRequested = false
  const ctrl = new AbortController()
  abortCtrl = ctrl
  stickToBottom = true

  try {
    let finished = false
    try {
      finished = await pumpChat(
        streamChat(
          {
            user_id: userId,
            session_id: session.id,
            message: userText,
            city: sessionCity.value || undefined,
            regenerate,
          },
          ctrl.signal,
        ),
        msg,
        session,
      )
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        handleAbort(msg, session)
        return
      }
      // 连接中断：转到下方续传
    }

    // 断线续传：按已收到字符数补发，后台生成不会因连接断开而丢失
    if (!finished) {
      try {
        finished = await pumpChat(
          resumeChat(
            // 按 Unicode 码点计数，与后端 Python len() 保持一致
            { userId, sessionId: session.id, offset: [...msg.content].length },
            ctrl.signal,
          ),
          msg,
          session,
        )
      } catch (e: any) {
        if (e?.name === 'AbortError') {
          handleAbort(msg, session)
          return
        }
        msg.status = 'error'
        msg.error = e?.message || '网络异常，请稍后重试'
        return
      }
    }
    if (msg.status === 'streaming') msg.status = 'done'
  } finally {
    if (abortCtrl === ctrl) abortCtrl = null
    chatStore.streaming = false
    await nextTick()
    scrollToBottom()
  }
}

async function send(text: string) {
  const content = text.trim()
  if (!content || chatStore.streaming) return

  const session = await ensureActiveSession()
  if (!session) return

  const user: ChatMessage = {
    id: uid('m'),
    role: 'user',
    content,
    createdAt: Date.now(),
    status: 'done',
  }
  chatStore.messages.push(user)
  if (!session.title) session.title = content.replace(/\s+/g, ' ').slice(0, 18)
  session.updatedAt = Date.now()

  await nextTick()
  scrollToBottom(true)
  await runAssistant(session, content)
}

async function regenerate() {
  const session = activeSession.value
  if (!session || chatStore.streaming) return
  const lastAssistant = [...chatStore.messages]
    .reverse()
    .find((m) => m.role === 'assistant')
  if (!lastAssistant) return
  const index = chatStore.messages.findIndex((m) => m.id === lastAssistant.id)
  if (index >= 0) chatStore.messages.splice(index, 1)
  const lastUser = [...chatStore.messages].reverse().find((m) => m.role === 'user')
  if (!lastUser) return
  await runAssistant(session, '', true)
}

const planLoading = ref(false)

/**
 * 进入快速开始前，先从会话记忆 + 最近对话提取表单字段。
 * 后端失败会自己降级；前端再兜底用最后一句用户消息，保证一定能进表单。
 */
async function goPlan() {
  const sessionId = chatStore.activeId
  if (!sessionId || planLoading.value) return

  planLoading.value = true
  const lastUser = lastUserContent()
  const localPrefs = PREF_KEYS.filter((k) => lastUser.includes(k))
  let prefill: TripPrefill = {
    city: sessionCity.value || undefined,
    preferences: localPrefs.length ? localPrefs : undefined,
    free_text_input: lastUser.slice(0, 120) || undefined,
    user_id: userId,
    session_id: sessionId,
  }

  try {
    const { prefill: remote } = await suggestTripPrefill({ userId, sessionId })
    const preferences = Array.from(
      new Set([...(remote.preferences || []), ...localPrefs]),
    )
    prefill = {
      city: remote.city || sessionCity.value || undefined,
      origin_city: remote.origin_city || undefined,
      start_date: remote.start_date || undefined,
      end_date: remote.end_date || undefined,
      travel_days: (remote.travel_days ?? 0) > 0 ? remote.travel_days : undefined,
      transportation: remote.transportation || undefined,
      accommodation: remote.accommodation || undefined,
      preferences: preferences.length ? preferences : undefined,
      free_text_input:
        remote.free_text_input || lastUser.slice(0, 120) || undefined,
      user_id: userId,
      session_id: sessionId,
    }
  } catch {
    // 网络/服务异常：保留本地兜底预填，不阻断进入表单
  } finally {
    planLoading.value = false
  }

  tripStore.prefill = prefill
  router.push('/quick-start')
}

/* ------- 滚动 ------- */
function onScroll() {
  const el = scrollEl.value
  if (!el) return
  stickToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  showJump.value = !stickToBottom
}

function scrollToBottom(force = false) {
  const el = scrollEl.value
  if (!el) return
  if (!force && !stickToBottom) return
  el.scrollTop = el.scrollHeight
  showJump.value = false
}

function jumpToBottom() {
  stickToBottom = true
  scrollToBottom(true)
}

function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') sidebarOpen.value = false
}

onMounted(async () => {
  window.addEventListener('keydown', onGlobalKeydown)
  await loadSessions()
  if (!chatStore.sessions.length) {
    await newSession()
  } else if (chatStore.activeId) {
    await loadMessages(chatStore.activeId)
  }
  await nextTick()
  scrollToBottom(true)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  abortCtrl?.abort()
})
</script>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
}
.chat-body {
  display: flex;
  flex: 1;
  min-height: 0;
}
.chat-main {
  position: relative;
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  background: #ffffff;
}
.chat-toolbar {
  display: flex;
  flex: none;
  align-items: center;
  gap: 12px;
  height: 56px;
  padding: 0 24px;
  border-bottom: 1px solid var(--hairline);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
.chat-menu-btn {
  display: none;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--ink-soft);
  font-size: 17px;
  cursor: pointer;
}
.chat-menu-btn:hover {
  background: var(--surface-2);
}
.chat-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--display);
  font-weight: 500;
  font-size: 15px;
  letter-spacing: 0.01em;
  color: var(--ink);
}
.chat-kb-btn {
  flex: none;
  margin-left: auto;
  height: 34px;
  padding: 0 14px;
  border: 0;
  border-radius: 999px;
  background: var(--blue-50);
  font-family: var(--font);
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: 0.01em;
  color: var(--blue-dark);
  cursor: pointer;
  transition: background 0.18s;
}
.chat-kb-btn:hover {
  background: var(--blue-100);
}
.chat-mode {
  flex: none;
  margin-left: 0;
  padding: 3px 8px;
  border: 1px solid var(--hairline);
  border-radius: 999px;
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.chat-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.chat-thread {
  width: min(800px, calc(100% - 56px));
  margin: 0 auto;
  padding: 40px 0 30px;
}
.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 58vh;
  text-align: center;
}
.chat-empty-title {
  margin: 20px 0 0;
  font-family: var(--display);
  font-size: 30px;
  font-weight: 500;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.chat-empty-sub {
  max-width: 440px;
  margin: 12px 0 0;
  font-size: 14px;
  line-height: 1.8;
  color: var(--ink-soft);
}
.chat-suggestions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  width: min(560px, 100%);
  margin-top: 34px;
}
.chat-suggestion {
  padding: 14px 16px;
  border: 1px solid var(--hairline);
  border-radius: 14px;
  background: #ffffff;
  font-family: var(--font);
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink-soft);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s, color 0.18s, background 0.18s, box-shadow 0.18s;
}
.chat-suggestion:hover {
  border-color: #c6dafc;
  background: var(--blue-50);
  color: var(--blue-dark);
  box-shadow: var(--shadow-1);
}
.chat-jump {
  position: absolute;
  left: 50%;
  bottom: 126px;
  z-index: 5;
  transform: translateX(-50%);
  height: 34px;
  padding: 0 16px;
  border: 1px solid var(--hairline);
  border-radius: 999px;
  background: #ffffff;
  font-family: var(--font);
  font-size: 12px;
  color: var(--ink-soft);
  cursor: pointer;
  box-shadow: var(--shadow-2);
}
.chat-jump:hover {
  border-color: #c6dafc;
  color: var(--blue-dark);
}
.chat-composer-shell {
  flex: none;
  border-top: 1px solid var(--hairline);
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

@media (max-width: 860px) {
  .chat-menu-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .chat-toolbar {
    padding: 0 14px;
  }
  .chat-thread {
    width: calc(100% - 32px);
    padding-top: 28px;
  }
  .chat-suggestions {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .chat-empty-title {
    font-size: 25px;
  }
  .chat-jump {
    bottom: 112px;
  }
  .chat-mode {
    display: none;
  }
  .chat-kb-btn {
    padding: 0 10px;
    font-size: 11.5px;
  }
}
</style>
