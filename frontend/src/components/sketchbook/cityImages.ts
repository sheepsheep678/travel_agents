/**
 * 城市页插图解析。
 *
 * 图片约定：把「全幅透明 PNG（1760×1240）」放进
 *   frontend/src/assets/sketchbook/<slug>.png
 * slug 为拼音小写（见 data/sketchbookCities.ts）。左侧放城市地标插画，
 * 右侧刻意留白（HTML 表单会盖在右页上）。
 *
 * 用 import.meta.glob 在构建期感知哪些图片已就位；缺失时退回内联 SVG
 * （纸底 + 衬线城市名 + 墨迹笔触），保证图片未提供时也能完整翻书。
 */
import type { SketchbookCity } from '../../data/sketchbookCities'

const modules = import.meta.glob('../../assets/sketchbook/*.png', {
  eager: true,
  import: 'default',
}) as Record<string, string>

const bySlug: Record<string, string> = {}
for (const [path, url] of Object.entries(modules)) {
  const base = path.split('/').pop() ?? ''
  bySlug[base.replace(/\.png$/i, '')] = url
}

function escapeXml(s: string): string {
  return s.replace(/[<>&'"]/g, (c) => {
    switch (c) {
      case '<': return '&lt;'
      case '>': return '&gt;'
      case '&': return '&amp;'
      case "'": return '&apos;'
      default: return '&quot;'
    }
  })
}

function fallbackSvg(name: string, en: string): string {
  const n = escapeXml(name)
  const e = escapeXml(en.toUpperCase())
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="1760" height="1240" viewBox="0 0 1760 1240">` +
    `<rect width="1760" height="1240" fill="#ece7dc"/>` +
    `<rect x="56" y="56" width="1648" height="1128" rx="18" fill="none" stroke="rgba(43,39,33,0.16)" stroke-width="2"/>` +
    `<line x1="880" y1="120" x2="880" y2="1120" stroke="rgba(43,39,33,0.10)" stroke-width="2"/>` +
    `<text x="440" y="600" text-anchor="middle" font-family="Georgia,'Songti SC','SimSun',serif" font-size="164" fill="#2b2721">${n}</text>` +
    `<text x="440" y="690" text-anchor="middle" font-family="Georgia,serif" font-size="40" letter-spacing="10" fill="rgba(43,39,33,0.45)">${e}</text>` +
    `<path d="M 250 760 C 350 720 530 720 630 760" fill="none" stroke="rgba(154,106,62,0.5)" stroke-width="3" stroke-linecap="round"/>` +
    `</svg>`
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
}

/** 解析某城市的页面图 URL（含兜底） */
export function cityPageSrc(city: SketchbookCity): string {
  return bySlug[city.slug] ?? fallbackSvg(city.name, city.en)
}
