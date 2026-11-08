<template>
  <footer class="site-footer">
    <div class="site-shell">
      <div class="site-footer-inner">
        <div class="site-footer-brand">
          <SealMark size="xs" />
          <span>旅迹智绘</span>
        </div>
        <p class="site-footer-note">让每次出发都有据可循 · 真实地点 · 实时天气 · 个性行程</p>
        <nav class="site-footer-nav" aria-label="页脚导航">
          <router-link to="/">首页</router-link>
          <router-link to="/quick-start">快速开始</router-link>
          <router-link to="/chat">AI 对话</router-link>
        </nav>
      </div>
      <p class="site-footer-copy">© 2026 旅迹智绘</p>
    </div>
  </footer>
</template>

<script setup lang="ts">
import SealMark from './SealMark.vue'
</script>
