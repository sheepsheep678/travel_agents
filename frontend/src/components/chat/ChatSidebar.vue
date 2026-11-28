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
  width: 276px;
  border-right: 1px solid var(--hairline);
  background: var(--surface);
}
.sidebar-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 14px 10px;
}
.sidebar-new {
  flex: 1;
  height: 42px;
  border: 0;
  border-radius: 999px;
  background: var(--blue-50);
  font-family: var(--font);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.01em;
  color: var(--blue-dark);
  cursor: pointer;
  transition: background 0.18s;
}
.sidebar-new:hover {
  background: var(--blue-100);
}
.sidebar-close {
  display: none;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--ink-soft);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}
.sidebar-close:hover {
  background: var(--surface-2);
}
.sidebar-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 10px;
}
.sidebar-empty {
  margin: 28px 8px;
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--ink-faint);
  text-align: center;
}
.sidebar-item {
  display: flex;
  align-items: center;
  gap: 4px;
  border-radius: 10px;
  transition: background 0.18s;
}
.sidebar-item:hover {
  background: var(--surface-2);
}
.sidebar-item.active {
  background: var(--blue-50);
}
.sidebar-item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 8px 10px 12px;
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
.sidebar-item.active .sidebar-item-title {
  color: var(--blue-dark);
  font-weight: 500;
}
.sidebar-item-time {
  font-size: 10.5px;
  letter-spacing: 0.01em;
  color: var(--ink-faint);
}
.sidebar-item-remove {
  flex: none;
  width: 28px;
  height: 28px;
  margin-right: 4px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--ink-faint);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.18s, color 0.18s, background 0.18s;
}
.sidebar-item:hover .sidebar-item-remove,
.sidebar-item.active .sidebar-item-remove {
  opacity: 1;
}
.sidebar-item-remove:hover {
  color: var(--seal);
  background: rgba(217, 48, 37, 0.08);
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
    background: #ffffff;
    transform: translateX(-100%);
    transition: transform 0.28s cubic-bezier(0.2, 0.7, 0.3, 1);
    box-shadow: var(--shadow-2);
  }
  .chat-sidebar.open {
    transform: translateX(0);
  }
  .sidebar-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 55;
    background: rgba(32, 33, 36, 0.32);
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
