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
  padding-top: 66px;
}

/* ---- Hero ---- */
.hero {
  display: grid;
  grid-template-columns: 1.06fr 0.94fr;
  gap: 54px;
  align-items: center;
}
.hero-kicker {
  margin: 0;
  font-size: 11px;
  letter-spacing: var(--track-caps);
  color: var(--earth);
  text-transform: uppercase;
}
.hero-title {
  margin: 20px 0 0;
  font-family: var(--display);
  font-weight: 400;
  font-size: clamp(40px, 5.2vw, 66px);
  line-height: 1.16;
  letter-spacing: 0.01em;
  color: var(--ink);
}
.hero-sub {
  max-width: 520px;
  margin: 24px 0 0;
  font-size: 15px;
  line-height: 1.9;
  color: var(--ink-soft);
}
.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 32px;
}
.hero-cities {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 7px 15px;
  margin: 36px 0 0;
  padding: 0;
  list-style: none;
}
.hero-cities-label {
  font-size: 10.5px;
  letter-spacing: var(--track-caps);
  color: var(--ink-faint);
  text-transform: uppercase;
}
.hero-cities a {
  font-size: 12px;
  color: var(--ink-soft);
  text-decoration: none;
  border-bottom: 1px solid transparent;
  transition: color 0.2s, border-color 0.2s;
}
.hero-cities a:hover {
  color: var(--earth);
  border-bottom-color: var(--earth);
}
.hero-cities-total {
  padding-left: 15px;
  border-left: 1px solid var(--hairline);
  font-size: 11.5px;
  color: var(--ink-faint);
}

/* ---- Hero 明信片 ---- */
.hero-art {
  position: relative;
  min-height: 400px;
}
.postcard {
  position: absolute;
  margin: 0;
  padding: 10px 10px 30px;
  background: rgba(255, 252, 244, 0.72);
  border: 1px solid var(--hairline);
  box-shadow: 0 26px 54px -34px rgba(43, 39, 33, 0.55);
}
.postcard-frame {
  position: relative;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: var(--paper);
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
  margin-top: 9px;
  text-align: right;
  font-family: var(--display);
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--ink-faint);
  text-transform: uppercase;
}
.postcard.front {
  z-index: 2;
  top: 34px;
  right: 0;
  width: 74%;
  transform: rotate(2.2deg);
}
.postcard.back {
  z-index: 1;
  top: 0;
  left: 0;
  width: 58%;
  opacity: 0.9;
  transform: rotate(-4deg);
}
.art-note {
  position: absolute;
  z-index: 3;
  font-family: var(--display);
  font-size: 12.5px;
  letter-spacing: 0.08em;
  color: var(--earth);
}
.art-note::after {
  content: '';
  display: block;
  margin-top: 4px;
  border-bottom: 1px dashed currentColor;
  opacity: 0.5;
}
.note-b {
  right: 1%;
  top: 2px;
  transform: rotate(2deg);
}

/* ---- 双入口 ---- */
.entries {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  margin-top: 78px;
}
.entry-card {
  display: flex;
  align-items: flex-start;
  gap: 18px;
  padding: 26px 28px 24px;
  background: rgba(255, 252, 244, 0.5);
  border: 1px solid var(--hairline);
  border-radius: 4px;
  color: var(--ink);
  text-decoration: none;
  transition: transform 0.25s, border-color 0.25s, box-shadow 0.25s, background 0.25s;
}
.entry-card:hover {
  transform: translateY(-3px);
  border-color: rgba(43, 39, 33, 0.3);
  background: rgba(255, 252, 244, 0.78);
  box-shadow: 0 22px 42px -32px rgba(43, 39, 33, 0.65);
}
.entry-index {
  padding-top: 5px;
  font-family: var(--display);
  font-size: 12px;
  letter-spacing: 0.14em;
  color: var(--ink-faint);
}
.entry-body {
  flex: 1;
}
.entry-title {
  margin: 0;
  font-family: var(--display);
  font-weight: 400;
  font-size: 24px;
  letter-spacing: 0.03em;
}
.entry-title em {
  margin-left: 10px;
  padding: 2px 7px;
  border: 1px solid rgba(179, 64, 42, 0.35);
  border-radius: 2px;
  font-family: var(--font);
  font-style: normal;
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--seal);
  vertical-align: 4px;
}
.entry-desc {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.75;
  color: var(--ink-soft);
}
.entry-arrow {
  font-size: 17px;
  color: var(--ink-faint);
  transition: transform 0.25s, color 0.25s;
}
.entry-card:hover .entry-arrow {
  transform: translateX(4px);
  color: var(--ink);
}

/* ---- 响应式 ---- */
@media (max-width: 960px) {
  .hero {
    grid-template-columns: 1fr;
    gap: 42px;
  }
  .hero-art {
    min-height: 330px;
    max-width: 540px;
  }
  .entries {
    grid-template-columns: 1fr;
    margin-top: 58px;
  }
}

@media (max-width: 560px) {
  .landing-main {
    padding-top: 38px;
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
    padding-left: 0;
    border-left: 0;
  }
  .entries {
    margin-top: 44px;
  }
}
</style>
