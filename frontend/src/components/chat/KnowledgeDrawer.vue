<template>
  <Teleport to="body">
    <transition name="kd-fade">
      <div v-if="open" class="kd-backdrop" @click="emit('close')"></div>
    </transition>

    <transition name="kd-slide">
      <aside
        v-if="open"
        class="kd-panel"
        role="dialog"
        aria-modal="true"
        aria-label="知识库"
      >
        <header class="kd-head">
          <div>
            <p class="kd-kicker">YOUR NOTES</p>
            <h2 class="kd-title">知识库</h2>
          </div>
          <button class="kd-close" aria-label="关闭知识库" @click="emit('close')">×</button>
        </header>

        <div class="kd-tabs" role="tablist">
          <button
            class="kd-tab"
            :class="{ active: tab === 'upload' }"
            role="tab"
            :aria-selected="tab === 'upload'"
            @click="tab = 'upload'"
          >
            上传
          </button>
          <button
            class="kd-tab"
            :class="{ active: tab === 'list' }"
            role="tab"
            :aria-selected="tab === 'list'"
            @click="tab = 'list'"
          >
            已上传<template v-if="items.length">（{{ items.length }}）</template>
          </button>
        </div>

        <div class="kd-body">
          <form v-if="tab === 'upload'" class="kd-form" @submit.prevent="submit">
            <button
              v-if="items.length"
              type="button"
              class="kd-jump-list"
              @click="tab = 'list'"
            >
              已上传 {{ items.length }} 条，去查看 / 删除
            </button>

            <label class="kd-drop" :class="{ has: !!file }" @dragover.prevent @drop.prevent="onDrop">
              <input
                ref="fileInput"
                class="kd-file-input"
                type="file"
                accept=".md,.txt,.pdf,.png,.jpg,.jpeg,.webp"
                @change="onFile"
              />
              <template v-if="file">
                <span class="kd-file-icon">📄</span>
                <span class="kd-file-name">{{ file.name }}</span>
                <span class="kd-file-size">{{ formatSize(file.size) }}</span>
                <button type="button" class="kd-file-remove" @click.prevent.stop="clearFile">
                  移除
                </button>
              </template>
              <template v-else>
                <span class="kd-drop-plus">＋</span>
                <span class="kd-drop-title">点击选择，或把文件拖到这里</span>
                <span class="kd-drop-hint">MD / TXT / PDF / 截图，单文件 ≤ 10MB</span>
              </template>
            </label>

            <label class="kd-label">
              文本
              <textarea
                v-model="text"
                class="kd-textarea"
                :maxlength="MAX_TEXT"
                rows="5"
                placeholder="粘贴攻略、路线或注意事项，例如：Day1 栈桥 → 八大关 → 五四广场…"
              ></textarea>
              <span class="kd-counter">{{ text.length }} / {{ MAX_TEXT }}</span>
            </label>

            <div class="kd-row">
              <label class="kd-label">
                标题（可选）
                <input v-model="title" class="kd-input" maxlength="60" placeholder="例如：我的青岛行程" />
              </label>
              <label class="kd-label">
                城市（可选）
                <input v-model="city" class="kd-input" maxlength="20" placeholder="例如：青岛" />
              </label>
            </div>

            <p v-if="error" class="kd-error">{{ error }}</p>

            <button class="kd-submit" type="submit" :disabled="uploading || (!file && !text.trim())">
              {{ uploading ? '解析并入库中…' : '上传并入库' }}
            </button>
          </form>

          <div v-else class="kd-list">
            <div class="kd-list-head">
              <span>已上传 {{ items.length }} 条</span>
              <button class="kd-refresh" type="button" :disabled="loading" @click="load">
                刷新
              </button>
            </div>

            <div v-if="loading" class="kd-empty">正在读取…</div>
            <div v-else-if="listError" class="kd-empty kd-error">{{ listError }}</div>
            <div v-else-if="!items.length" class="kd-empty">
              还没有上传内容<br />
              补一段自己的攻略，规划时会优先参考。
            </div>

            <article v-for="item in items" :key="item.doc_id" class="kd-item">
              <div class="kd-item-head">
                <span class="kd-badge">{{ badge(item.source_type) }}</span>
                <h3 class="kd-item-title">{{ item.title }}</h3>
                <button
                  class="kd-item-del"
                  type="button"
                  aria-label="删除这条内容"
                  @click="remove(item)"
                >
                  删除
                </button>
              </div>
              <p class="kd-item-preview">{{ item.preview }}</p>
              <p class="kd-item-meta">
                {{ item.chunk_count }} 段 · {{ fmtTime(item.created_at) }}
                <span v-if="item.city"> · {{ item.city }}</span>
              </p>
            </article>
          </div>
        </div>

        <footer class="kd-foot">
          资料仅对当前浏览器可见<span class="kd-id"> · ID {{ sessionId.slice(0, 8) }}</span>
          <br />规划时会与管理端知识库一起检索。
        </footer>
      </aside>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { deleteKnowledge, listKnowledge, uploadKnowledge } from '../../services/api'
import type { KnowledgeItem } from '../../types'

const props = defineProps<{
  open: boolean
  sessionId: string
}>()

const emit = defineEmits<{
  close: []
  uploaded: [item: KnowledgeItem]
}>()

const MAX_FILE_MB = 10
const MAX_FILE = MAX_FILE_MB * 1024 * 1024
const MAX_TEXT = 20000
const ALLOWED_EXT = ['.md', '.txt', '.pdf', '.png', '.jpg', '.jpeg', '.webp']

const tab = ref<'upload' | 'list'>('upload')
const fileInput = ref<HTMLInputElement>()
const file = ref<File | null>(null)
const text = ref('')
const title = ref('')
const city = ref('')
const uploading = ref(false)
const error = ref('')
const items = ref<KnowledgeItem[]>([])
const loading = ref(false)
const listError = ref('')

function formatSize(size: number): string {
  if (size < 1024) return `${size}B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${(size / 1024 / 1024).toFixed(1)}MB`
}

function badge(type: string): string {
  return ({ md: 'MD', txt: 'TXT', pdf: 'PDF', image: 'IMG' } as Record<string, string>)[type]
    || (type || 'TXT').toUpperCase()
}

function fmtTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function setFile(picked: File) {
  error.value = ''
  const dot = picked.name.lastIndexOf('.')
  const ext = dot >= 0 ? picked.name.slice(dot).toLowerCase() : ''
  if (!ALLOWED_EXT.includes(ext)) {
    error.value = '不支持的文件类型，请上传 MD / TXT / PDF / 图片'
    return
  }
  if (picked.size > MAX_FILE) {
    error.value = `文件超过 ${MAX_FILE_MB}MB`
    return
  }
  file.value = picked
}

function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  const picked = input.files?.[0]
  if (picked) setFile(picked)
  input.value = ''
}

function onDrop(event: DragEvent) {
  const picked = event.dataTransfer?.files?.[0]
  if (picked) setFile(picked)
}

function clearFile() {
  file.value = null
  if (fileInput.value) fileInput.value.value = ''
}

let loadToken = 0

async function load() {
  if (!props.sessionId) return
  const token = ++loadToken
  loading.value = true
  listError.value = ''
  try {
    const response = await listKnowledge(props.sessionId)
    if (token !== loadToken) return
    // 与当前列表合并，避免“上传成功但较早的列表请求返回后把新条目覆盖掉”。
    const byId = new Map<string, KnowledgeItem>()
    for (const item of items.value) byId.set(item.doc_id, item)
    for (const item of response.items || []) byId.set(item.doc_id, item)
    items.value = [...byId.values()].sort((a, b) =>
      (b.created_at || '').localeCompare(a.created_at || ''),
    )
  } catch (e: any) {
    if (token === loadToken) {
      listError.value = e?.response?.data?.detail || e?.message || '读取失败'
    }
  } finally {
    if (token === loadToken) loading.value = false
  }
}

async function submit() {
  const content = text.value.trim()
  if (!file.value && !content) return

  const formData = new FormData()
  formData.append('session_id', props.sessionId)
  if (file.value) formData.append('file', file.value)
  if (content) formData.append('text', content)
  if (title.value.trim()) formData.append('title', title.value.trim())
  if (city.value.trim()) formData.append('city', city.value.trim())

  uploading.value = true
  error.value = ''
  try {
    const response = await uploadKnowledge(formData)
    if (!response.success) throw new Error(response.message || '上传失败')
    if (response.item) {
      items.value = [
        response.item,
        ...items.value.filter((item) => item.doc_id !== response.item!.doc_id),
      ]
      emit('uploaded', response.item)
    }
    message.success('已存入知识库')
    listError.value = ''
    text.value = ''
    title.value = ''
    city.value = ''
    clearFile()
    tab.value = 'list'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '上传失败'
  } finally {
    uploading.value = false
  }
}

function remove(item: KnowledgeItem) {
  Modal.confirm({
    title: '删除这条内容？',
    content: item.title,
    okText: '删除',
    cancelText: '取消',
    okButtonProps: { danger: true },
    async onOk() {
      try {
        await deleteKnowledge(item.doc_id, props.sessionId)
        items.value = items.value.filter((entry) => entry.doc_id !== item.doc_id)
        message.success('已删除')
      } catch (e: any) {
        message.error(e?.response?.data?.detail || e?.message || '删除失败')
        throw e
      }
    },
  })
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open) emit('close')
}

watch(
  () => props.open,
  (open) => {
    if (open) load()
  },
)

watch(
  () => props.sessionId,
  () => {
    items.value = []
    listError.value = ''
    loadToken += 1
    if (props.open) load()
  },
)

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  if (props.open) load()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.kd-backdrop {
  position: fixed;
  inset: 0;
  z-index: 65;
  background: rgba(43, 39, 33, 0.28);
}

.kd-panel {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 70;
  display: flex;
  flex-direction: column;
  width: min(400px, 92vw);
  border-right: 1px solid var(--hairline, rgba(43, 39, 33, 0.18));
  background: var(--paper, #ece7dc);
  box-shadow: 24px 0 60px -34px rgba(43, 39, 33, 0.55);
}

.kd-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 22px 20px 14px;
}

.kd-kicker {
  margin: 0 0 6px;
  font-size: 10px;
  letter-spacing: 0.18em;
  color: var(--ink-faint, #8d8578);
}

.kd-title {
  margin: 0;
  font-family: var(--display, Georgia, serif);
  font-size: 24px;
  font-weight: 400;
  letter-spacing: 0.03em;
  color: var(--ink, #2b2721);
}

.kd-close {
  flex: none;
  width: 32px;
  height: 32px;
  border: 0;
  background: transparent;
  color: var(--ink-soft, #5f584d);
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}

.kd-close:hover {
  color: var(--seal, #b3402a);
}

.kd-tabs {
  display: flex;
  gap: 20px;
  padding: 0 20px;
  border-bottom: 1px solid var(--hairline, rgba(43, 39, 33, 0.18));
}

.kd-tab {
  position: relative;
  padding: 10px 0;
  border: 0;
  background: transparent;
  font-family: var(--font, Georgia, serif);
  font-size: 13px;
  letter-spacing: 0.04em;
  color: var(--ink-faint, #8d8578);
  cursor: pointer;
}

.kd-tab.active {
  color: var(--ink, #2b2721);
}

.kd-tab.active::after {
  content: '';
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  background: var(--seal, #b3402a);
}

.kd-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px 24px;
}

.kd-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.kd-jump-list {
  padding: 8px 10px;
  border: 1px dashed var(--hairline, rgba(43, 39, 33, 0.28));
  border-radius: 3px;
  background: rgba(255, 252, 244, 0.5);
  font-family: var(--font, Georgia, serif);
  font-size: 11px;
  letter-spacing: 0.03em;
  color: var(--ink-soft, #5f584d);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}

.kd-jump-list:hover {
  border-color: var(--ink, #2b2721);
  color: var(--ink, #2b2721);
}

.kd-drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 132px;
  padding: 16px;
  border: 1px dashed var(--hairline, rgba(43, 39, 33, 0.28));
  border-radius: 4px;
  background: rgba(255, 252, 244, 0.42);
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}

.kd-drop:hover,
.kd-drop.has {
  border-color: var(--ink, #2b2721);
  background: rgba(255, 252, 244, 0.72);
}

.kd-file-input {
  display: none;
}

.kd-drop-plus {
  font-size: 24px;
  color: var(--ink-faint, #8d8578);
}

.kd-drop-title {
  font-size: 13px;
  color: var(--ink-soft, #5f584d);
}

.kd-drop-hint {
  font-size: 10.5px;
  color: var(--ink-faint, #8d8578);
}

.kd-file-icon {
  font-size: 22px;
}

.kd-file-name {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--ink, #2b2721);
}

.kd-file-size {
  font-size: 10.5px;
  color: var(--ink-faint, #8d8578);
}

.kd-file-remove {
  margin-top: 4px;
  border: 0;
  background: transparent;
  font-size: 11px;
  color: var(--seal, #b3402a);
  text-decoration: underline;
  cursor: pointer;
}

.kd-label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-soft, #5f584d);
}

.kd-textarea,
.kd-input {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 10px;
  border: 1px solid var(--hairline, rgba(43, 39, 33, 0.18));
  border-radius: 3px;
  background: rgba(255, 252, 244, 0.55);
  font-family: var(--font, Georgia, serif);
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink, #2b2721);
  outline: none;
  resize: vertical;
}

.kd-textarea:focus,
.kd-input:focus {
  border-color: rgba(43, 39, 33, 0.42);
  background: rgba(255, 252, 244, 0.9);
}

.kd-counter {
  align-self: flex-end;
  font-size: 10px;
  color: var(--ink-faint, #8d8578);
}

.kd-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.kd-error {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--seal, #b3402a);
}

.kd-submit {
  height: 40px;
  border: 1px solid var(--ink, #2b2721);
  border-radius: 3px;
  background: var(--ink, #2b2721);
  font-family: var(--font, Georgia, serif);
  font-size: 13px;
  letter-spacing: 0.06em;
  color: var(--paper, #ece7dc);
  cursor: pointer;
  transition: background 0.2s, opacity 0.2s;
}

.kd-submit:hover:not(:disabled) {
  background: var(--earth, #9a6a3e);
}

.kd-submit:disabled {
  opacity: 0.35;
  cursor: default;
}

.kd-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.kd-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 2px;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--ink-faint, #8d8578);
}

.kd-refresh {
  padding: 2px 7px;
  border: 1px solid var(--hairline, rgba(43, 39, 33, 0.18));
  border-radius: 2px;
  background: transparent;
  font-family: var(--font, Georgia, serif);
  font-size: 10.5px;
  color: var(--ink-soft, #5f584d);
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}

.kd-refresh:hover:not(:disabled) {
  border-color: var(--ink, #2b2721);
  color: var(--ink, #2b2721);
}

.kd-refresh:disabled {
  opacity: 0.4;
  cursor: default;
}

.kd-empty {
  padding: 36px 8px;
  font-size: 12px;
  line-height: 1.9;
  color: var(--ink-faint, #8d8578);
  text-align: center;
}

.kd-item {
  padding: 13px 14px;
  border: 1px solid var(--hairline, rgba(43, 39, 33, 0.18));
  border-radius: 4px;
  background: rgba(255, 252, 244, 0.5);
}

.kd-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.kd-badge {
  flex: none;
  padding: 2px 5px;
  border: 1px solid var(--hairline, rgba(43, 39, 33, 0.22));
  border-radius: 2px;
  font-size: 9px;
  letter-spacing: 0.08em;
  color: var(--ink-faint, #8d8578);
}

.kd-item-title {
  flex: 1;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font, Georgia, serif);
  font-size: 13px;
  font-weight: 400;
  color: var(--ink, #2b2721);
}

.kd-item-del {
  flex: none;
  padding: 3px 7px;
  border: 1px solid transparent;
  border-radius: 2px;
  background: transparent;
  font-family: var(--font, Georgia, serif);
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--seal, #b3402a);
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}

.kd-item-del:hover {
  border-color: var(--seal, #b3402a);
  background: rgba(179, 64, 42, 0.06);
}

.kd-item-preview {
  display: -webkit-box;
  margin: 8px 0 0;
  overflow: hidden;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  font-size: 12px;
  line-height: 1.75;
  color: var(--ink-soft, #5f584d);
  white-space: pre-wrap;
  word-break: break-word;
}

.kd-item-meta {
  margin: 8px 0 0;
  font-size: 10px;
  letter-spacing: 0.04em;
  color: var(--ink-faint, #8d8578);
}

.kd-foot {
  flex: none;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--hairline, rgba(43, 39, 33, 0.18));
  font-size: 10px;
  line-height: 1.6;
  color: var(--ink-faint, #8d8578);
}

.kd-id {
  color: var(--ink-faint, #8d8578);
  letter-spacing: 0.02em;
}

.kd-fade-enter-active,
.kd-fade-leave-active {
  transition: opacity 0.25s;
}

.kd-fade-enter-from,
.kd-fade-leave-to {
  opacity: 0;
}

.kd-slide-enter-active,
.kd-slide-leave-active {
  transition: transform 0.28s ease;
}

.kd-slide-enter-from,
.kd-slide-leave-to {
  transform: translateX(-100%);
}

@media (max-width: 560px) {
  .kd-panel {
    width: 100%;
  }
  .kd-head {
    padding: 18px 16px 12px;
  }
  .kd-tabs {
    padding: 0 16px;
  }
  .kd-body {
    padding: 16px;
  }
  .kd-row {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .kd-fade-enter-active,
  .kd-fade-leave-active,
  .kd-slide-enter-active,
  .kd-slide-leave-active {
    transition: none;
  }
}
</style>
