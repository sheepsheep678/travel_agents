<template>
  <transition name="sidebar-fade">
    <div v-if="open" class="sidebar-backdrop" @click="$emit('close')"></div>
  </transition>

  <aside id="chat-sidebar" class="chat-sidebar" :class="{ open }" aria-label="历史对话">
    <div class="sidebar-head">
      <button class="sidebar-new" @click="$emit('new')">＋ 新的对话</button>
      <button class="sidebar-close" aria-label="关闭会话列表" @click="$emit('close')">×</button>
    </div>

    <nav class="sidebar-list">
      <p v-if="!sessions.length" class="sidebar-empty">还没有对话<br />从一个问题开始吧</p>
      <div
        v-for="s in sessions"
        :key="s.id"
        class="sidebar-item"
        :class="{ active: s.id === activeId }"
      >
        <button class="sidebar-item-main" @click="$emit('select', s.id)">
          <span class="sidebar-item-title">{{ s.title || '新的对话' }}</span>
          <span class="sidebar-item-time">{{ fmtTime(s.updatedAt) }}</span>
        </button>
        <button class="sidebar-item-remove" aria-label="删除对话" @click.stop="$emit('remove', s.id)">×</button>
      </div>
    </nav>

    <p class="sidebar-foot">对话与知识库记录保存在当前浏览器。</p>
  </aside>
</template>

<script setup lang="ts">
import type { ChatSession } from '../../types'

defineProps<{
  sessions: ChatSession[]
  activeId: string | null
  open: boolean
}>()

defineEmits<{
  new: []
  select: [id: string]
  remove: [id: string]
  close: []
}>()

function fmtTime(ts: number): string {
  const d = new Date(ts)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}
</script>

<style scoped>
.chat-sidebar {
  display: flex;
  flex-direction: column;
  flex: none;
  width: 272px;
  border-right: 1px solid var(--hairline);
  background: rgba(255, 252, 244, 0.28);
}
.sidebar-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 16px 10px;
}
.sidebar-new {
  flex: 1;
  height: 40px;
  border: 1px solid var(--hairline);
  border-radius: 3px;
  background: transparent;
  font-family: var(--font);
  font-size: 13px;
  letter-spacing: 0.04em;
  color: var(--ink);
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}
.sidebar-new:hover {
  border-color: var(--ink);
  background: rgba(43, 39, 33, 0.04);
}
.sidebar-close {
  display: none;
  width: 32px;
  height: 32px;
  border: 0;
  background: transparent;
  color: var(--ink-soft);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}
.sidebar-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 10px;
}
.sidebar-empty {
  margin: 26px 8px;
  font-size: 12px;
  line-height: 1.9;
  color: var(--ink-faint);
  text-align: center;
}
.sidebar-item {
  display: flex;
  align-items: center;
  gap: 4px;
  border-left: 2px solid transparent;
  border-radius: 2px;
  transition: background 0.2s, border-color 0.2s;
}
.sidebar-item:hover {
  background: rgba(43, 39, 33, 0.04);
}
.sidebar-item.active {
  border-left-color: var(--seal);
  background: rgba(255, 252, 244, 0.7);
}
.sidebar-item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 8px 10px 10px;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.sidebar-item-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font);
  font-size: 13px;
  color: var(--ink);
}
.sidebar-item-time {
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--ink-faint);
}
.sidebar-item-remove {
  flex: none;
  width: 26px;
  height: 26px;
  margin-right: 4px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--ink-faint);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s, color 0.2s;
}
.sidebar-item:hover .sidebar-item-remove,
.sidebar-item.active .sidebar-item-remove {
  opacity: 1;
}
.sidebar-item-remove:hover {
  color: var(--seal);
}
.sidebar-foot {
  margin: 0;
  padding: 12px 16px 16px;
  border-top: 1px solid var(--hairline);
  font-size: 10.5px;
  line-height: 1.65;
  color: var(--ink-faint);
}

.sidebar-backdrop {
  display: none;
}

.sidebar-fade-enter-active,
.sidebar-fade-leave-active {
  transition: opacity 0.25s;
}
.sidebar-fade-enter-from,
.sidebar-fade-leave-to {
  opacity: 0;
}

@media (max-width: 860px) {
  .chat-sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 60;
    width: min(300px, 84vw);
    background: var(--paper);
    transform: translateX(-100%);
    transition: transform 0.28s ease;
  }
  .chat-sidebar.open {
    transform: translateX(0);
  }
  .sidebar-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 55;
    background: rgba(43, 39, 33, 0.28);
  }
  .sidebar-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .sidebar-item-remove {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .chat-sidebar {
    transition: none;
  }
  .sidebar-fade-enter-active,
  .sidebar-fade-leave-active {
    transition: none;
  }
}
</style>
