import { createRouter, createWebHistory } from 'vue-router'
import Landing from '../views/Landing.vue'
import QuickStart from '../views/QuickStart.vue'
import Chat from '../views/Chat.vue'
import Result from '../views/Result.vue'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Landing, meta: { title: '旅迹智绘 · 把一座城写成一页旅程' } },
    { path: '/quick-start', name: 'quick-start', component: QuickStart, meta: { title: '快速开始 · 旅迹智绘' } },
    { path: '/chat', name: 'chat', component: Chat, meta: { title: 'AI 对话 · 旅迹智绘' } },
    { path: '/result', name: 'result', component: Result, meta: { title: '我的旅行计划 · 旅迹智绘' } },
  ],
})

router.afterEach((to) => {
  document.title = to.meta.title ?? '旅迹智绘 · 手账旅行计划'
})

export default router
