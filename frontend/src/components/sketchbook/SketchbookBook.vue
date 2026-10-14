<template>
  <div class="sb-wrap">
    <div ref="stageEl" class="sb-stage">
      <button class="sb-arrow left" aria-label="上一页" @click="step('next')">
        <svg viewBox="0 0 14 44" width="14" height="44" fill="none" aria-hidden="true">
          <polyline points="11,3 3,22 11,41" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>

      <div ref="sb3dEl" class="sb-3d">
        <div class="sb-tilt">
          <div class="sb-cast ambient" aria-hidden="true"></div>
          <div class="sb-cast contact" aria-hidden="true"></div>
          <div class="sb-cast hair" aria-hidden="true"></div>
          <div ref="bookEl" class="sb-book"></div>
        </div>
        <!-- 表单/进度覆盖层：压在右页上，是 .sb-tilt 的兄弟节点（不受 3D 变换影响） -->
        <div class="sb-sheet"><slot name="sheet" /></div>
      </div>

      <button class="sb-arrow right" aria-label="下一页" @click="step('prev')">
        <svg viewBox="0 0 14 44" width="14" height="44" fill="none" aria-hidden="true">
          <polyline points="3,3 11,22 3,41" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>

    <div class="sb-captions">
      <p class="sb-caption">{{ pages[shownIdx]?.name }}</p>
    </div>
    <p class="sb-hint">拖动左页翻页 · 键盘 ← → · 点击下方城市直达</p>

    <div class="sb-dots" role="list">
      <button
        v-for="(c, i) in pages"
        :key="c.slug"
        role="listitem"
        class="sb-dot"
        :class="{ active: i === shownIdx }"
        :aria-current="i === shownIdx ? 'true' : 'false'"
        @click="goTo(i)"
      >
        {{ c.name }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import type { SketchbookCity } from '../../data/sketchbookCities'
import { cityPageSrc } from './cityImages'

const props = defineProps<{ pages: SketchbookCity[] }>()
const idx = defineModel<number>('index', { required: true })
// 翻页过程中「正在展示」的那一页：caption / 圆点高亮实时跟随翻页目标，
// 避免翻页时画面已切到目标城市、文字仍停留在旧城市（两者错位）。
const shownIdx = ref(0)

const stageEl = ref<HTMLElement>()
const sb3dEl = ref<HTMLElement>()
const bookEl = ref<HTMLElement>()

/* ------------------------------------------------- 几何常量（与参考一致） */
const N = 18 // 翻页叶的条带数
const SPAN = 0.5 // 中缝 → 页外沿，占书宽比例（全出血图片，页宽 = 半页）
const BETA = 0.60 // 翻页弧的峰值曲率（弧度）
const TILT_X = 4.5
const TILT_Y = 7

/* 逐帧动画状态：普通闭包变量，不进 Vue 响应式（避免每帧触发重渲染） */
interface Turn {
  dir: 'next' | 'prev'
  from: number
  to: number
  t: number
}
interface Drag {
  dir: 'next' | 'prev'
  x0: number
  w: number
  moved: number
  vel: number
  tPrev: number
}
interface Spring {
  v: number
  target: number
  done?: () => void
  k: number
  c: number
}

let turn: Turn | null = null
let drag: Drag | null = null
let spring: Spring | null = null
let strips: HTMLElement[] = []
let raf = 0
let last = 0
const view = { rx: 0, ry: 0, z: 1, trx: 0, try_: 0, tz: 1 }
let viewActive = false

const REDUCED = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches

/* ----------------------------------------------------- DOM 构造 */
function el(t: string, c?: string): HTMLElement {
  const e = document.createElement(t)
  if (c) e.className = c
  return e
}

function imgEl(city: SketchbookCity, side?: string): HTMLImageElement {
  const im = new Image()
  im.className = side ? 'sb-half-img ' + side : ''
  im.draggable = false
  im.alt = ''
  im.src = cityPageSrc(city)
  return im
}

function halfEl(pos: 'left' | 'right', city: SketchbookCity): HTMLElement {
  const d = el('div', 'sb-half ' + pos)
  d.appendChild(imgEl(city, pos))
  d.appendChild(el('div', 'gutter-shade ' + pos))
  return d
}

/** 构建翻页叶：由嵌套条带组成的一张真实曲面 */
function buildCurl(dir: 'next' | 'prev', from: number, to: number): HTMLElement {
  strips = []
  const c = el('div', 'curl ' + dir)
  c.style.setProperty('--n', String(N))
  c.style.setProperty('--span', String(SPAN))
  let host = c
  const fromUrl = cityPageSrc(props.pages[from])
  const toUrl = cityPageSrc(props.pages[to])
  for (let i = 0; i < N; i++) {
    const s = el('div', 'strip')
    const gut = 'calc(var(--bw) * 0.5)'
    const sw = 'calc(var(--bw) * ' + SPAN + ' / ' + N + ')'
    const A = 'calc(-1 * (' + gut + ' + ' + i + ' * ' + sw + '))' // 朝「来自页」
    const B = 'calc(' + (i + 1) + ' * ' + sw + ' - ' + gut + ')' // 朝「去向页」
    const f = el('div', 'face front')
    const b = el('div', 'face back')
    const dress = (e: HTMLElement, url: string, px: string) => {
      e.style.backgroundImage = 'url(' + url + ')'
      e.style.backgroundPositionX = px
    }
    dress(f, fromUrl, dir === 'next' ? A : B)
    dress(b, toUrl, dir === 'next' ? B : A)
    f.appendChild(el('div', 'sh'))
    f.appendChild(el('div', 'gl'))
    b.appendChild(el('div', 'sh'))
    b.appendChild(el('div', 'gl'))
    s.appendChild(f)
    s.appendChild(b)
    if (i === N - 1) s.classList.add('edge')
    host.appendChild(s)
    host = s
    strips.push(s)
  }
  return c
}

function applyTurn(t: number): void {
  // 翻过一半即把展示城市切到目标页，让 caption/圆点与画面同步
  if (turn) shownIdx.value = t >= 0.5 ? turn.to : turn.from
  if (!sb3dEl.value) return
  const th = Math.PI * t
  const beta = BETA * Math.sin(Math.PI * t)
  const D = 180 / Math.PI
  const tt = th + beta
  const td = (2 * beta) / N
  sb3dEl.value.style.setProperty('--tt', (tt * D).toFixed(2) + 'deg')
  sb3dEl.value.style.setProperty('--td', (td * D).toFixed(3) + 'deg')
  sb3dEl.value.style.setProperty('--shade', Math.sin(Math.PI * t).toFixed(3))
  for (let i = 0; i < strips.length; i++) {
    const l1 = Math.abs(Math.cos(tt - i * td))
    const l2 = Math.abs(Math.cos(tt - (i + 1) * td))
    const st = strips[i].style
    st.setProperty('--lit', l1.toFixed(3))
    st.setProperty('--a1', ((1 - l1) * 0.62).toFixed(3))
    st.setProperty('--a2', ((1 - l2) * 0.62).toFixed(3))
  }
}

function paint(): void {
  if (!bookEl.value || !sb3dEl.value) return
  bookEl.value.textContent = ''
  if (!turn) {
    const i = Math.min(Math.max(0, idx.value), props.pages.length - 1)
    shownIdx.value = i
    const f = el('div', 'sb-full')
    const im = new Image()
    im.src = cityPageSrc(props.pages[i])
    im.alt = props.pages[i].name
    im.draggable = false
    f.appendChild(im)
    bookEl.value.appendChild(f)
    sb3dEl.value.style.setProperty('--shade', '0')
  } else {
    const next = turn.dir === 'next'
    bookEl.value.appendChild(halfEl('left', props.pages[next ? turn.from : turn.to]))
    bookEl.value.appendChild(halfEl('right', props.pages[next ? turn.to : turn.from]))
    bookEl.value.appendChild(buildCurl(turn.dir, turn.from, turn.to))
    applyTurn(turn.t)
  }
  const a = el('button', 'sb-zone sb-prev')
  const b = el('button', 'sb-zone sb-next')
  a.setAttribute('aria-label', '上一页')
  b.setAttribute('aria-label', '下一页')
  bookEl.value.appendChild(a)
  bookEl.value.appendChild(b)
  layout()
}

function layout(): void {
  if (!sb3dEl.value || !bookEl.value) return
  sb3dEl.value.style.setProperty('--bw', bookEl.value.clientWidth + 'px')
}

/* ------------------------------------------------------ 弹簧循环 */
function animateTo(target: number, onDone?: () => void, stiff = 150, damp = 22): void {
  spring = { v: 0, target, done: onDone, k: stiff, c: damp }
  kick()
}

function tick(now: number): void {
  raf = 0
  const dt = Math.min(0.032, (now - last) / 1000 || 0.016)
  last = now
  if (spring && turn) {
    const s = spring
    const x = turn.t - s.target
    s.v += (-s.k * x - s.c * s.v) * dt
    turn.t += s.v * dt
    if (Math.abs(turn.t - s.target) < 0.002 && Math.abs(s.v) < 0.02) {
      turn.t = s.target
      spring = null
      applyTurn(turn.t)
      const d = s.done
      d && d()
    } else {
      applyTurn(turn.t)
    }
  }
  viewSpring()
  if ((spring || viewActive) && raf === 0) raf = requestAnimationFrame(tick)
}

function kick(): void {
  if (raf === 0) {
    last = performance.now()
    raf = requestAnimationFrame(tick)
  }
}

/* ------------------------------------------- 书本随光标倾斜 */
function applyView(): void {
  if (!sb3dEl.value) return
  sb3dEl.value.style.setProperty('--rx', view.rx.toFixed(2) + 'deg')
  sb3dEl.value.style.setProperty('--ry', view.ry.toFixed(2) + 'deg')
  sb3dEl.value.style.setProperty('--zoom', view.z.toFixed(3))
}

function viewSpring(): boolean {
  const e = 0.14
  let moved = false
  const d1 = view.trx - view.rx
  if (Math.abs(d1) > 0.0006) { view.rx += d1 * e; moved = true } else view.rx = view.trx
  const d2 = view.try_ - view.ry
  if (Math.abs(d2) > 0.0006) { view.ry += d2 * e; moved = true } else view.ry = view.try_
  const d3 = view.tz - view.z
  if (Math.abs(d3) > 0.0006) { view.z += d3 * e; moved = true } else view.z = view.tz
  if (moved) applyView()
  viewActive = moved
  return moved
}

function setView(rx: number, ry: number, z: number): void {
  view.trx = Math.max(-TILT_X, Math.min(TILT_X, rx))
  view.try_ = Math.max(-TILT_Y, Math.min(TILT_Y, ry))
  view.tz = z
  viewActive = true
  kick()
}

function tiltTo(cx: number, cy: number): void {
  if (drag || !bookEl.value) return
  const r = bookEl.value.getBoundingClientRect()
  if (!r.width) return
  const nx = Math.max(-1, Math.min(1, (cx - (r.left + r.width / 2)) / (r.width * 0.62)))
  const ny = Math.max(-1, Math.min(1, (cy - (r.top + r.height / 2)) / (r.height * 0.9)))
  setView(-ny * TILT_X, nx * TILT_Y, view.tz)
}

function onPointerMoveWin(e: PointerEvent): void {
  if (e.pointerType === 'touch') return
  tiltTo(e.clientX, e.clientY)
}
function onPointerOutWin(e: PointerEvent): void {
  if (!e.relatedTarget) setView(0, 0, view.tz)
}
function onBlurWin(): void {
  setView(0, 0, view.tz)
}

/* ------------------------------------------------------- 指针翻页 */
function onPointerDown(e: PointerEvent): void {
  if (e.button !== 0) return
  const target = e.target as HTMLElement
  // 让表单/控件自然处理，绝不捕获、绝不 preventDefault
  if (target.closest('.sb-sheet, .ant-select, .ant-picker, .ant-input, .ant-input-number, textarea')) return
  const onBook = target.closest('.sb-zone')
  if (!onBook || !bookEl.value || !stageEl.value) return
  e.preventDefault()
  stageEl.value.setPointerCapture(e.pointerId)
  const r = bookEl.value.getBoundingClientRect()
  const dir: 'next' | 'prev' = (e.clientX - r.left) / r.width > 0.5 ? 'next' : 'prev'
  startTurn(dir, 0)
  drag = { dir, x0: e.clientX, w: r.width, moved: 0, vel: 0, tPrev: performance.now() }
}

function onPointerMove(e: PointerEvent): void {
  if (!drag) return
  const dx = e.clientX - drag.x0
  drag.moved = Math.max(drag.moved, Math.abs(dx))
  const raw = (drag.dir === 'next' ? -dx : dx) / (drag.w * 0.62)
  const t = Math.max(0, Math.min(1, raw))
  const now = performance.now()
  drag.vel = (t - (turn ? turn.t : 0)) / Math.max(0.001, (now - drag.tPrev) / 1000)
  drag.tPrev = now
  if (turn) {
    turn.t = t
    applyTurn(t)
  }
}

function endDrag(): void {
  if (!drag) return
  const d = drag
  drag = null
  if (!turn) return
  if (d.moved < 6) {
    commit()
    return
  }
  const go = turn.t > 0.42 || d.vel > 1.1
  if (go) commit()
  else cancel()
}

/* ------------------------------------------------------ 翻页控制 */
function startTurn(dir: 'next' | 'prev', t: number): void {
  spring = null
  if (turn) {
    idx.value = turn.to
    turn = null
  }
  const M = props.pages.length
  const from = idx.value
  // 翻页方向：左页右翻 = 下一页、右页左翻 = 上一页。
  // 因此 dir='prev'（左页）实际 → from+1，dir='next'（右页）实际 → from-1。
  turn = { dir, from, to: dir === 'next' ? (from - 1 + M) % M : (from + 1) % M, t: t || 0 }
  paint()
}

function commit(): void {
  const t = turn
  if (!t) return
  if (REDUCED) {
    idx.value = t.to
    turn = null
    paint()
    return
  }
  animateTo(
    1,
    () => {
      idx.value = t.to
      turn = null
      paint()
    },
    170,
    26
  )
  kick()
}

function cancel(): void {
  if (!turn) return
  animateTo(0, () => {
    turn = null
    paint()
  }, 150, 24)
  kick()
}

function step(dir: 'next' | 'prev'): void {
  if (turn) {
    idx.value = turn.to
    turn = null
  }
  startTurn(dir, 0)
  commit()
}

function goTo(i: number): void {
  if (i === idx.value) return
  if (turn) {
    spring = null
    idx.value = turn.to
    turn = null
  }
  const M = props.pages.length
  const fwd = (i - idx.value + M) % M
  const back = (idx.value - i + M) % M
  if (Math.min(fwd, back) === 1) {
    step(fwd === 1 ? 'prev' : 'next')
    return
  }
  idx.value = i
  paint()
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const t = e.target as HTMLElement
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
  if (t && t.closest('.ant-select, .ant-picker')) return
  e.preventDefault()
  step(e.key === 'ArrowRight' ? 'prev' : 'next')
}

function onDragStart(e: Event): void {
  e.preventDefault()
}
function onSelectStart(e: Event): void {
  e.preventDefault()
}

function preload(): void {
  props.pages.forEach((c) => {
    const im = new Image()
    im.src = cityPageSrc(c)
    im.decode?.().catch(() => {})
  })
}

function bind(): void {
  const s = stageEl.value
  if (s) {
    s.addEventListener('pointerdown', onPointerDown)
    s.addEventListener('pointermove', onPointerMove)
    s.addEventListener('pointerup', endDrag)
    s.addEventListener('pointercancel', endDrag)
    s.addEventListener('dragstart', onDragStart)
    s.addEventListener('selectstart', onSelectStart)
  }
  window.addEventListener('pointermove', onPointerMoveWin, { passive: true })
  window.addEventListener('pointerout', onPointerOutWin)
  window.addEventListener('blur', onBlurWin)
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', layout)
}

function unbind(): void {
  const s = stageEl.value
  if (s) {
    s.removeEventListener('pointerdown', onPointerDown)
    s.removeEventListener('pointermove', onPointerMove)
    s.removeEventListener('pointerup', endDrag)
    s.removeEventListener('pointercancel', endDrag)
    s.removeEventListener('dragstart', onDragStart)
    s.removeEventListener('selectstart', onSelectStart)
  }
  window.removeEventListener('pointermove', onPointerMoveWin)
  window.removeEventListener('pointerout', onPointerOutWin)
  window.removeEventListener('blur', onBlurWin)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', layout)
}

onMounted(() => {
  paint()
  applyView()
  preload()
  bind()
})

onUnmounted(() => {
  unbind()
  if (raf) cancelAnimationFrame(raf)
  raf = 0
})

// idx 变化即强制重绘（动画进行中不打断，动画结束回调会自行 paint 并同步 shownIdx）
watch(idx, (newIdx) => {
  if (turn) return
  shownIdx.value = newIdx
  paint()
})

// pages 变化时清理动画状态并校验索引，避免越界 / 残留弹簧空转
watch(
  () => props.pages,
  (pages) => {
    spring = null
    drag = null
    turn = null
    if (!pages.length) {
      shownIdx.value = 0
      if (bookEl.value) bookEl.value.replaceChildren()
      return
    }
    idx.value = Math.min(Math.max(0, idx.value), pages.length - 1)
    shownIdx.value = idx.value
    paint()
  }
)
</script>

<style>
/* ============ 手账翻书（非 scoped：书页内容由 JS 动态构造，需全局样式） ============ */
.sb-wrap {
  display: grid;
  justify-items: center;
  gap: 18px;
  width: 100%;
  position: relative;
  z-index: 2;
}
.sb-stage {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  position: relative;
  touch-action: pan-y;
}
.sb-arrow {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 2px;
  border: 0;
  background: transparent;
  color: var(--ink-faint);
  cursor: pointer;
  transition: color 0.2s;
  -webkit-tap-highlight-color: transparent;
  z-index: 8;
}
.sb-arrow:hover {
  color: var(--ink);
}

/* 书的未变换外框：loupe 级的浮层放这里，只有 .sb-tilt 在其下倾斜缩放 */
.sb-3d {
  position: relative;
  flex: 1 1;
  min-width: 0;
  max-width: 900px;
  perspective: 1750px;
  perspective-origin: 50% 46%;
}
.sb-tilt {
  position: relative;
  transform-style: preserve-3d;
  transform: rotateX(var(--rx, 0deg)) rotateY(var(--ry, 0deg)) scale(var(--zoom, 1));
  will-change: transform;
}
.sb-book {
  position: relative;
  width: 100%;
  aspect-ratio: 1760 / 1240;
  transform-style: preserve-3d;
  z-index: 1;
}

/* 桌面上柔和的阴影池 */
.sb-cast {
  position: absolute;
  pointer-events: none;
  z-index: 0;
}
.sb-cast.ambient {
  left: 5%;
  right: 5%;
  top: 27%;
  bottom: 2%;
  background: radial-gradient(50% 50% at 50% 58%, rgba(58, 44, 26, 0.34) 0%, rgba(58, 44, 26, 0.19) 40%, rgba(58, 44, 26, 0) 74%);
  filter: blur(26px);
  opacity: calc(1 - var(--shade, 0) * 0.42);
}
.sb-cast.contact {
  left: 9%;
  right: 9%;
  top: 62%;
  bottom: 10%;
  background: radial-gradient(50% 44% at 50% 42%, rgba(44, 32, 14, 0.4) 0%, rgba(44, 32, 14, 0.17) 48%, rgba(44, 32, 14, 0) 78%);
  filter: blur(11px);
  opacity: calc(1 - var(--shade, 0) * 0.5);
}
.sb-cast.hair {
  left: 12%;
  right: 12%;
  top: 70%;
  bottom: 17%;
  background: radial-gradient(50% 52% at 50% 40%, rgba(40, 28, 10, 0.34) 0%, rgba(40, 28, 10, 0) 76%);
  filter: blur(4px);
  opacity: calc(1 - var(--shade, 0) * 0.62);
}

.sb-full {
  position: absolute;
  inset: 0;
}
.sb-full img {
  width: 100%;
  height: auto;
  display: block;
  user-select: none;
  -webkit-user-drag: none;
}
.sb-half {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 50%;
  overflow-x: clip;
  overflow-y: visible;
}
.sb-half.left {
  left: 0;
}
.sb-half.right {
  left: 50%;
}
.sb-half-img {
  width: 200%;
  max-width: none;
  height: auto;
  display: block;
  user-select: none;
  -webkit-user-drag: none;
}
.sb-half-img.right {
  margin-left: -100%;
}

/* 抬起叶投到下方页上的阴影 */
.gutter-shade {
  position: absolute;
  top: var(--pg, 0%);
  bottom: var(--pg, 0%);
  width: 46%;
  pointer-events: none;
  opacity: calc(var(--shade, 0) * 0.62);
  -webkit-mask-image: linear-gradient(180deg, transparent 0, #000 5.2%, #000 94.8%, transparent 100%);
  mask-image: linear-gradient(180deg, transparent 0, #000 5.2%, #000 94.8%, transparent 100%);
}
.gutter-shade.left {
  right: 0;
  background: linear-gradient(270deg, rgba(52, 38, 20, 0.3), rgba(52, 38, 20, 0) 82%);
}
.gutter-shade.right {
  left: 0;
  background: linear-gradient(90deg, rgba(52, 38, 20, 0.24), rgba(52, 38, 20, 0) 82%);
}

/* 翻页叶：嵌套条带形成曲面 */
.curl {
  position: absolute;
  top: 0;
  height: 100%;
  width: calc(var(--bw, 0px) * var(--span));
  transform-style: preserve-3d;
  z-index: 6;
}
.curl.next {
  left: 50%;
  transform-origin: left center;
  transform: rotateY(calc(-1 * var(--tt, 0deg)));
}
.curl.prev {
  right: 50%;
  transform-origin: right center;
  transform: rotateY(var(--tt, 0deg));
}
.strip {
  position: absolute;
  top: 0;
  height: 100%;
  width: calc(var(--bw, 0px) * var(--span) / var(--n));
  transform-style: preserve-3d;
}
.curl.next .strip {
  transform-origin: left center;
}
.curl.prev .strip {
  transform-origin: right center;
}
.curl.next > .strip {
  left: 0;
}
.curl.prev > .strip {
  right: 0;
  left: auto;
}
.curl.next .strip .strip {
  left: 100%;
  transform: rotateY(var(--td, 0deg));
}
.curl.prev .strip .strip {
  right: 100%;
  transform: rotateY(calc(-1 * var(--td, 0deg)));
}
.face {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  right: -1.1px;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
  background-repeat: no-repeat;
  background-size: var(--bw, 0px) auto;
}
.face.back {
  transform: rotateY(180deg);
}
.face .sh,
.face .gl {
  -webkit-mask-image: linear-gradient(180deg, transparent 0, #000 5.2%, #000 94.8%, transparent 100%);
  mask-image: linear-gradient(180deg, transparent 0, #000 5.2%, #000 94.8%, transparent 100%);
}
.strip.edge .face .sh,
.strip.edge .face .gl {
  -webkit-mask-image: linear-gradient(180deg, transparent 0, #000 9%, #000 91%, transparent 100%), var(--hf);
  mask-image: linear-gradient(180deg, transparent 0, #000 9%, #000 91%, transparent 100%), var(--hf);
  -webkit-mask-composite: source-in;
  mask-composite: intersect;
}
.curl.next .strip.edge .face.front,
.curl.prev .strip.edge .face.back {
  --hf: linear-gradient(90deg, #000 0 22%, transparent 96%);
}
.curl.next .strip.edge .face.back,
.curl.prev .strip.edge .face.front {
  --hf: linear-gradient(270deg, #000 0 22%, transparent 96%);
}
.face .sh {
  position: absolute;
  left: 0;
  right: 0;
  top: var(--pg, 0%);
  bottom: var(--pg, 0%);
  pointer-events: none;
}
.curl.next .face.front .sh,
.curl.prev .face.back .sh {
  background: linear-gradient(90deg, rgba(58, 43, 20, var(--a1, 0)), rgba(58, 43, 20, var(--a2, 0)));
}
.curl.next .face.back .sh,
.curl.prev .face.front .sh {
  background: linear-gradient(90deg, rgba(58, 43, 20, var(--a2, 0)), rgba(58, 43, 20, var(--a1, 0)));
}
.face .gl {
  position: absolute;
  left: 0;
  right: 0;
  top: var(--pg, 0%);
  bottom: var(--pg, 0%);
  pointer-events: none;
  background: #fffaf0;
  opacity: calc(var(--shade, 0) * var(--lit, 1) * var(--lit, 1) * 0.2);
}

/* 翻页点击区 */
.sb-zone {
  position: absolute;
  top: 0;
  bottom: 0;
  border: 0;
  background: transparent;
  cursor: grab;
  z-index: 60;
  -webkit-tap-highlight-color: transparent;
}
.sb-zone:active {
  cursor: grabbing;
}
.sb-prev {
  left: 0;
  width: 50%;
}
.sb-next {
  right: 0;
  width: 50%;
}

/* 表单/进度覆盖层：压在右页上（桌面）；移动端改静态流布局 */
.sb-sheet {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 43%;
  z-index: 20;
  box-sizing: border-box;
  padding: 6% 4% 6% 7%;
  overflow-y: auto;
}
.sb-sheet > * {
  width: 100%;
}
.sb-sheet::-webkit-scrollbar {
  width: 6px;
}
.sb-sheet::-webkit-scrollbar-thumb {
  background: rgba(43, 39, 33, 0.18);
}

.sb-captions {
  display: grid;
  justify-items: center;
  min-height: 30px;
}
.sb-caption {
  margin: 0;
  font-family: var(--display);
  font-size: 24px;
  letter-spacing: 0.04em;
  color: var(--ink);
}
.sb-hint {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--ink-faint);
}

.sb-dots {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px 8px;
  max-width: 720px;
  padding: 0 8px;
}
.sb-dot {
  border: 0;
  background: transparent;
  color: var(--ink-faint);
  cursor: pointer;
  font-family: var(--font);
  font-size: 13px;
  letter-spacing: 0.04em;
  padding: 3px 10px;
  border-radius: 999px;
  transition: color 0.2s, background-color 0.2s;
}
.sb-dot:hover {
  color: var(--ink);
}
.sb-dot.active {
  color: var(--paper);
  background: var(--ink);
}

@media (max-width: 900px) {
  .sb-arrow {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    z-index: 70;
    padding: 12px 6px;
  }
  .sb-arrow.left {
    left: 2px;
  }
  .sb-arrow.right {
    right: 2px;
  }
  .sb-3d {
    max-width: none;
  }
  .sb-sheet {
    position: static;
    width: 100%;
    left: 0;
    padding: 24px 8px 8px;
    overflow: visible;
  }
  .sb-hint {
    font-size: 9.5px;
    letter-spacing: 0.1em;
    padding: 0 16px;
    text-align: center;
  }
}
</style>
