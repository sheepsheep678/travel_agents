import { onUnmounted } from 'vue'

/**
 * 手账纸墨主题的 body 类管理。
 *
 * `--paper` / `--ink` 等 token 与 antd 弹层主题都挂在 `.sketchbook-mode` 上，
 * 页面级重复 add/remove 容易在路由切换时残留或闪白，这里用引用计数统一管理。
 * 在 setup 中同步调用，避免首帧拿不到变量。
 */
let activeCount = 0

export function usePaperTheme() {
  activeCount += 1
  document.body.classList.add('sketchbook-mode')

  onUnmounted(() => {
    activeCount = Math.max(0, activeCount - 1)
    if (activeCount === 0) document.body.classList.remove('sketchbook-mode')
  })
}
