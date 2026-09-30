import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发时：前端跑在 5173，所有后端请求代理到 FastAPI 的 8000——
// 浏览器眼里同源，不用折腾跨域。构建时：产物输出到 dist/，交给 FastAPI 托管。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/scan': 'http://127.0.0.1:8000',
      '/identify': 'http://127.0.0.1:8000',
      '/generate': 'http://127.0.0.1:8000',
      '/study-path': 'http://127.0.0.1:8000',
      '/report': 'http://127.0.0.1:8000',
      '/cost': 'http://127.0.0.1:8000',
      '/sessions': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
})
