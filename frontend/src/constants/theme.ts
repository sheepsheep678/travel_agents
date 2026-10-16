/**
 * 手账主题色值的 JS 侧单一来源。
 *
 * 与 styles/sketchbook.css 的 CSS 变量 --paper / --ink 保持一致。
 * 之所以在这里再声明一遍：CSS 变量在 JS 里读不到，而 html2canvas 导出底色
 * （Result.vue）与缺图兜底 SVG（cityImages.ts）都必须拿到字面量。
 * 改色时两处一起改，否则导出图与页面会漂移。
 */
export const PAPER = '#ece7dc'
export const INK = '#2b2721'
