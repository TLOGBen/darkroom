/**
 * Vite 設定（開發伺服器、建置、測試）。
 *
 * - publicDir＝static/：logo、favicon 原樣複製到 dist 根目錄（plan-v2 §2）。
 * - build 輸出 web/dist，由 Python 伺服器供應頁面。
 * - dev proxy：/api → 後端（預設 127.0.0.1:8765；環境變數 DARKROOM_PORT 可改，例如 8799）。
 *   後端的 _local_only（darkroom_app/server.py）會檢查 Host 必須是 127.0.0.1:{埠} 或 localhost:{埠}、
 *   Origin 必須是頁面自己的來源、Sec-Fetch-Site 不能是 cross-site／same-site。
 *   瀏覽器在 5173 打開頁面時，這三個標頭描述的是 5173，所以 proxy 把它們改寫成後端自己的位址，
 *   後端看起來就跟頁面由它自己供應時一樣。X-Darkroom 與 Content-Type 由 requests/ 的 client 自己帶。
 */
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

const backendPort = Number(process.env.DARKROOM_PORT || 8765);
const backend = `http://127.0.0.1:${backendPort}`;

export default defineConfig({
  plugins: [react()],
  publicDir: 'static',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // MUI＋React 一包就超過 500 kB，這是本機 App，不在意首屏下載量
    chunkSizeWarningLimit: 1500,
  },
  server: {
    host: '127.0.0.1',
    // plan-v2 §2 的預設是 5173；Windows 有時把 5141～5240 劃給 Hyper-V（EACCES），可用 DARKROOM_WEB_PORT 換埠
    port: Number(process.env.DARKROOM_WEB_PORT || 5173),
    strictPort: true,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true, // Host → 127.0.0.1:<後端埠>
        configure(proxy) {
          proxy.on('proxyReq', (req) => {
            // Origin 只在瀏覽器有送時改寫（GET 通常沒有）；Sec-Fetch-Site 從 5173 的同源請求本來就是 same-origin，
            // 但為了不讓後端看到「5173 → 8765」的跨站判斷，一律拿掉。
            if (req.getHeader('origin')) req.setHeader('origin', backend);
            req.removeHeader('sec-fetch-site');
            req.removeHeader('referer');
          });
        },
      },
    },
  },
  preview: { host: '127.0.0.1', port: 4173 },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
});
