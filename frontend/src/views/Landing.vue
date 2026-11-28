<template>
  <div class="site-page landing">
    <PaperWash />
    <SiteHeader active="home" />

    <main class="site-shell landing-main">
      <section class="hero">
        <div class="hero-copy fade-up">
          <p class="hero-kicker">AI 旅行规划</p>
          <h1 class="hero-title">把一座城，<br />写成一页旅程。</h1>
          <p class="hero-sub">
            选一座城，写下日期和偏好，几分钟内得到一份可以直接出发的每日行程——景点、酒店、天气和预算都帮你安排妥当。
          </p>

          <div class="hero-actions">
            <router-link to="/quick-start" class="btn btn-ink">快速开始 <span aria-hidden="true">→</span></router-link>
            <router-link to="/chat" class="btn btn-ghost">和 AI 聊聊 <span aria-hidden="true">→</span></router-link>
          </div>

          <ul class="hero-cities" aria-label="热门城市">
            <li class="hero-cities-label">热门城市</li>
            <li v-for="c in hotCities" :key="c.slug">
              <router-link :to="{ path: '/quick-start', query: { city: c.name } }">{{ c.name }}</router-link>
            </li>
            <li class="hero-cities-total">已收录 {{ totalCities }} 个城市</li>
          </ul>
        </div>

        <div class="hero-art fade-up" aria-hidden="true">
          <figure class="postcard back">
            <div class="postcard-frame">
              <img :src="cityPageSrc(backCity)" alt="" />
            </div>
            <figcaption>{{ backCity.en }}</figcaption>
          </figure>
          <figure class="postcard front">
            <div class="postcard-frame">
              <img :src="cityPageSrc(frontCity)" alt="" />
            </div>
            <figcaption>{{ frontCity.en }}</figcaption>
          </figure>
          <span class="art-note note-b">真实地点 · 实时天气</span>
        </div>
      </section>

      <section class="entries" aria-label="选择开始方式">
        <router-link v-for="e in entries" :key="e.to" :to="e.to" class="entry-card">
          <span class="entry-index">{{ e.index }}</span>
          <div class="entry-body">
            <h2 class="entry-title">
              {{ e.title }}
              <em v-if="e.tag">{{ e.tag }}</em>
            </h2>
            <p class="entry-desc">{{ e.desc }}</p>
          </div>
          <span class="entry-arrow" aria-hidden="true">→</span>
        </router-link>
      </section>
    </main>

    <SiteFooter />
  </div>
</template>

<script setup lang="ts">
import PaperWash from '../components/site/PaperWash.vue'
import SiteHeader from '../components/site/SiteHeader.vue'
import SiteFooter from '../components/site/SiteFooter.vue'
import { usePaperTheme } from '../composables/usePaperTheme'
import { cityPageSrc } from '../components/sketchbook/cityImages'
import { sketchbookCities } from '../data/sketchbookCities'

usePaperTheme()

const frontCity = sketchbookCities[0]
const backCity = sketchbookCities[8]

/** 首页只展示 10 个热门城市（共 11 座），点击后用该城市打开快速开始。 */
const hotCities = sketchbookCities.slice(0, 10)

/** 已收录的城市总数（后续接真实数量） */
const totalCities = 694

const entries = [
  {
    to: '/quick-start',
    index: '01',
    title: '快速开始',
    desc: '选一座城，写下日期和偏好，几分钟内生成包含景点、酒店、天气与预算的完整行程。',
  },
  {
    to: '/chat',
    index: '02',
    title: 'AI 对话',
    tag: '新',
    desc: '像聊天一样说出想法，边聊边把目的地、节奏和住宿定下来，再开始规划。',
  },
]
</script>

<style scoped>
.landing-main {
  padding-top: 76px;
}

/* ---- Hero ---- */
.hero {
  display: grid;
  grid-template-columns: 1.08fr 0.92fr;
  gap: 64px;
  align-items: center;
}
.hero-kicker {
  margin: 0;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: var(--track-caps);
  color: var(--earth);
  text-transform: uppercase;
}
.hero-title {
  margin: 18px 0 0;
  font-family: var(--display);
  font-weight: 500;
  font-size: clamp(40px, 5.2vw, 64px);
  line-height: 1.14;
  letter-spacing: -0.015em;
  color: var(--ink);
}
.hero-sub {
  max-width: 540px;
  margin: 24px 0 0;
  font-size: 16px;
  line-height: 1.85;
  color: var(--ink-soft);
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 36px;
}
.hero-cities {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 4px;
  margin: 38px 0 0;
  padding: 0;
  list-style: none;
}
.hero-cities-label {
  margin-right: 6px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: var(--track-caps);
  color: var(--ink-faint);
  text-transform: uppercase;
}
.hero-cities a {
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--ink-soft);
  text-decoration: none;
  transition: color 0.18s, background 0.18s;
}
.hero-cities a:hover {
  color: var(--blue-dark);
  background: var(--blue-50);
}
.hero-cities-total {
  margin-left: 8px;
  padding-left: 14px;
  border-left: 1px solid var(--hairline);
  font-size: 12px;
  color: var(--ink-faint);
}

/* ---- Hero 明信片 ---- */
.hero-art {
  position: relative;
  min-height: 430px;
}
.hero-art::before {
  content: '';
  position: absolute;
  z-index: 0;
  top: 6%;
  right: -6%;
  width: 340px;
  height: 340px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, rgba(66, 133, 244, 0.16), rgba(66, 133, 244, 0) 68%);
  pointer-events: none;
}
.postcard {
  position: absolute;
  margin: 0;
  padding: 9px 9px 14px;
  background: #ffffff;
  border: 1px solid var(--hairline);
  border-radius: 20px;
  box-shadow: var(--shadow-2);
}
.postcard-frame {
  position: relative;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  border-radius: 13px;
  background: var(--surface);
}
/* 城市图是 1760×1240 的整页图，地标只在左半幅：放大到 ~1.9 倍后左对齐裁切 */
.postcard-frame img {
  position: absolute;
  left: 0;
  top: 50%;
  width: 190%;
  max-width: none;
  height: auto;
  transform: translateY(-50%);
}
.postcard figcaption {
  margin: 9px 4px 0;
  text-align: right;
  font-family: var(--display);
  font-weight: 500;
  font-size: 11px;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
  text-transform: uppercase;
}
.postcard.front {
  z-index: 2;
  top: 46px;
  right: 0;
  width: 76%;
}
.postcard.back {
  z-index: 1;
  top: 0;
  left: 0;
  width: 58%;
}
.postcard.back .postcard-frame {
  background: var(--surface-2);
}
.art-note {
  position: absolute;
  z-index: 3;
  padding: 7px 14px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid var(--hairline);
  box-shadow: var(--shadow-1);
  font-family: var(--display);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--ink-soft);
}
.art-note::before {
  content: '';
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 7px;
  border-radius: 50%;
  background: #34a853;
}
.note-b {
  right: 2%;
  top: 0;
}

/* ---- 双入口 ---- */
.entries {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  margin-top: 88px;
}
.entry-card {
  display: flex;
  align-items: flex-start;
  gap: 18px;
  padding: 28px 30px 26px;
  background: #ffffff;
  border: 1px solid var(--hairline);
  border-radius: 20px;
  color: var(--ink);
  text-decoration: none;
  transition: transform 0.25s, border-color 0.25s, box-shadow 0.25s;
}
.entry-card:hover {
  transform: translateY(-2px);
  border-color: #c6dafc;
  box-shadow: var(--shadow-2);
}
.entry-index {
  padding-top: 4px;
  font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--earth);
}
.entry-body {
  flex: 1;
}
.entry-title {
  margin: 0;
  font-family: var(--display);
  font-weight: 500;
  font-size: 22px;
  letter-spacing: 0.01em;
}
.entry-title em {
  margin-left: 10px;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--blue-50);
  font-family: var(--font);
  font-style: normal;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.08em;
  color: var(--blue-dark);
  vertical-align: 4px;
}
.entry-desc {
  margin: 10px 0 0;
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--ink-soft);
}
.entry-arrow {
  font-size: 18px;
  color: var(--ink-faint);
  transition: transform 0.25s, color 0.25s;
}
.entry-card:hover .entry-arrow {
  transform: translateX(4px);
  color: var(--earth);
}

/* ---- 响应式 ---- */
@media (max-width: 960px) {
  .hero {
    grid-template-columns: 1fr;
    gap: 42px;
  }
  .hero-art {
    min-height: 340px;
    max-width: 560px;
  }
  .entries {
    grid-template-columns: 1fr;
    margin-top: 64px;
  }
}

@media (max-width: 560px) {
  .landing-main {
    padding-top: 40px;
  }
  .hero-art {
    display: none;
  }
  .hero-title {
    font-size: clamp(32px, 10vw, 42px);
  }
  .hero-actions .btn {
    flex: 1;
    padding: 0 16px;
  }
  .hero-cities-total {
    width: 100%;
    margin-left: 0;
    padding-left: 0;
    border-left: 0;
  }
  .entries {
    margin-top: 48px;
  }
}
</style>
