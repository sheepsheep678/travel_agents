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
              :can-plan="!!sessionCity && m.id === lastAssistantId() && m.status === 'done'"
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
  createSession,
  deleteSession,
  getSession,
  listSessions,
  streamChat,
} from '../services/api'
import { sketchbookCities } from '../data/sketchbookCities'
import type { ChatMessage, ChatSession } from '../types'

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
  abortCtrl?.abort()
}

function stopIfStreaming() {
  if (chatStore.streaming) stop()
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
  if (id === chatStore.activeId) stopIfStreaming()
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
  const ctrl = new AbortController()
  abortCtrl = ctrl
  stickToBottom = true

  try {
    for await (const ev of streamChat(
      {
        user_id: userId,
        session_id: session.id,
        message: userText,
        city: sessionCity.value || undefined,
        regenerate,
      },
      ctrl.signal,
    )) {
      if (ev.type === 'token') {
        msg.content += ev.delta
        session.updatedAt = Date.now()
        await nextTick()
        scrollToBottom()
      } else if (ev.type === 'error') {
        msg.status = 'error'
        msg.error = ev.message
        break
      } else {
        if (ev.session_id && ev.session_id !== session.id) {
          // 理论上不会发生；保持本地状态与服务端一致
          session.id = ev.session_id
          chatStore.activeId = ev.session_id
        }
        msg.status = 'done'
        break
      }
    }
    if (msg.status === 'streaming') msg.status = 'done'
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      if (!msg.content) {
        const i = chatStore.messages.findIndex((m) => m.id === msg.id)
        if (i >= 0) chatStore.messages.splice(i, 1)
      } else {
        msg.status = 'stopped'
      }
    } else {
      msg.status = 'error'
      msg.error = e?.message || '网络异常，请稍后重试'
    }
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

function goPlan() {
  const lastUser = lastUserContent()
  const preferences = PREF_KEYS.filter((k) => lastUser.includes(k))
  tripStore.prefill = {
    city: sessionCity.value || undefined,
    preferences: preferences.length ? preferences : undefined,
    free_text_input: lastUser.slice(0, 120),
    user_id: userId,
    session_id: chatStore.activeId || undefined,
  }
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
}
.chat-toolbar {
  display: flex;
  flex: none;
  align-items: center;
  gap: 12px;
  height: 46px;
  padding: 0 28px;
  border-bottom: 1px solid var(--hairline);
  background: rgba(236, 231, 220, 0.6);
}
.chat-menu-btn {
  display: none;
  width: 30px;
  height: 30px;
  border: 0;
  background: transparent;
  color: var(--ink);
  font-size: 17px;
  cursor: pointer;
}
.chat-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--display);
  font-size: 15px;
  letter-spacing: 0.04em;
  color: var(--ink);
}
.chat-kb-btn {
  flex: none;
  margin-left: auto;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--hairline);
  border-radius: 3px;
  background: transparent;
  font-family: var(--font);
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--ink-soft);
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s, background 0.2s;
}
.chat-kb-btn:hover {
  border-color: var(--ink);
  background: rgba(255, 252, 244, 0.55);
  color: var(--ink);
}
.chat-mode {
  flex: none;
  margin-left: 0;
  padding: 3px 8px;
  border: 1px solid var(--hairline);
  border-radius: 2px;
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--ink-faint);
}
.chat-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.chat-thread {
  width: min(760px, calc(100% - 56px));
  margin: 0 auto;
  padding: 34px 0 26px;
}
.chat-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 54vh;
  text-align: center;
}
.chat-empty-title {
  margin: 18px 0 0;
  font-family: var(--display);
  font-size: 30px;
  font-weight: 400;
  letter-spacing: 0.03em;
  color: var(--ink);
}
.chat-empty-sub {
  max-width: 420px;
  margin: 12px 0 0;
  font-size: 13px;
  line-height: 1.85;
  color: var(--ink-soft);
}
.chat-suggestions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: min(520px, 100%);
  margin-top: 30px;
}
.chat-suggestion {
  padding: 12px 14px;
  border: 1px solid var(--hairline);
  border-radius: 4px;
  background: rgba(255, 252, 244, 0.5);
  font-family: var(--font);
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-soft);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s, background 0.2s;
}
.chat-suggestion:hover {
  border-color: var(--ink);
  background: rgba(255, 252, 244, 0.85);
  color: var(--ink);
}
.chat-jump {
  position: absolute;
  left: 50%;
  bottom: 118px;
  z-index: 5;
  transform: translateX(-50%);
  height: 30px;
  padding: 0 13px;
  border: 1px solid var(--hairline);
  border-radius: 999px;
  background: rgba(236, 231, 220, 0.94);
  font-family: var(--font);
  font-size: 11px;
  color: var(--ink-soft);
  cursor: pointer;
  box-shadow: 0 8px 20px -14px rgba(43, 39, 33, 0.6);
}
.chat-jump:hover {
  border-color: var(--ink);
  color: var(--ink);
}
.chat-composer-shell {
  flex: none;
  border-top: 1px solid var(--hairline);
  background: rgba(236, 231, 220, 0.82);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
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
    padding-top: 24px;
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
    bottom: 104px;
  }
  .chat-mode {
    display: none;
  }
  .chat-kb-btn {
    padding: 0 8px;
    font-size: 10.5px;
  }
}
</style>
