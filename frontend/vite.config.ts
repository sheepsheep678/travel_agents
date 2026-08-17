import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Agent 真实调用可能长达 5 分钟，所有代理/客户端超时都要留足
const LONG_TIMEOUT = 600000 // 10 分钟

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        timeout: LONG_TIMEOUT,
        proxyTimeout: LONG_TIMEOUT,
      },
    },
  },
})
