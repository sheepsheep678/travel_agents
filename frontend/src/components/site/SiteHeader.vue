<template>
  <header class="site-header">
    <div class="site-shell site-header-inner">
      <router-link to="/" class="site-brand" aria-label="旅迹智绘首页">
        <SealMark size="sm" />
        <span class="site-brand-name">旅迹智绘</span>
      </router-link>

      <nav class="site-nav" aria-label="主导航">
        <router-link
          v-for="item in nav"
          :key="item.key"
          :to="item.to"
          class="site-nav-link"
          :class="{ active: active === item.key }"
        >
          {{ item.label }}
        </router-link>
      </nav>

      <router-link to="/quick-start" class="site-header-cta">
        开始规划 <span aria-hidden="true">→</span>
      </router-link>
    </div>
  </header>
</template>

<script setup lang="ts">
import SealMark from './SealMark.vue'

type NavKey = 'home' | 'quick-start' | 'chat'

defineProps<{ active?: NavKey }>()

const nav: { key: NavKey; label: string; to: string }[] = [
  { key: 'home', label: '首页', to: '/' },
  { key: 'quick-start', label: '快速开始', to: '/quick-start' },
  { key: 'chat', label: 'AI 对话', to: '/chat' },
]
</script>
