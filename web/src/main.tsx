/**
 * 進入點：掛上 Provider（MUI 主題、i18n、TanStack Query、Router）後畫 App。
 *
 * - 一定要先 import global.scss：它輸出全部 --dr-* 變數，theme.ts 的元件覆寫都靠這些變數（DESIGN.md §2.4）。
 *   不要再加 <CssBaseline />（global.scss 已經做了它的事）。
 * - 主題預設深色；<html data-theme> 由 MUI 寫，index.html 的小腳本在 React 起來前就先套上記住的模式，避免閃白。
 * - i18n 在 import './i18n' 時初始化（語言：上次用的 → 瀏覽器 → zh-TW；設定讀回來後 App 再對齊）。
 */
import './styles/global.scss';
import './i18n';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ThemeProvider } from '@mui/material';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router';
import theme from './styles/theme';
import { queryClient } from './hooks/queries';
import { App } from './App';

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <ThemeProvider theme={theme} defaultMode="dark">
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
