import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Agent 真实调用可能长达 5 分钟，所有代理/客户端超时都要留足
const LONG_TIMEOUT = 600000 // 10 分钟

const apiProxy = {
  '/api': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
    timeout: LONG_TIMEOUT,
    proxyTimeout: LONG_TIMEOUT,
  },
}

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: apiProxy,
  },
  // npm run preview 时同样需要代理，否则 /api 请求会落到 4173 端口报 Network Error
  preview: {
    port: 4173,
    proxy: apiProxy,
  },
})
