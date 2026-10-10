/**
 * i18next 設定：zh-TW（預設）與 en-US 兩份語言檔，鍵完全一致（src/i18n/locales.test.ts 把關）。
 *
 * 語言怎麼決定（plan-v2 §2）：設定的 `language` → 瀏覽器語言 → zh-TW。
 * 一開始還沒讀到設定，先用「上次用的語言」（localStorage `darkroom.language`）或瀏覽器語言；
 * 設定讀回來後由 App 呼叫 `setLanguage()` 對齊。設定頁切換語言時也呼叫它，畫面立即換字。
 *
 * 非 React 的程式（zustand store、domain 的句子函式）用這裡匯出的 `tr` 當 Translate。
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zhTW from './locales/zh-TW.json';
import enUS from './locales/en-US.json';
import { pickLanguage, type Language } from '../domain/settings';
import type { Translate } from '../domain/text';

const STORAGE_KEY = 'darkroom.language';

function remembered(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export const initialLanguage: Language = pickLanguage(
  remembered(),
  typeof navigator !== 'undefined' ? navigator.languages : [],
);

void i18n.use(initReactI18next).init({
  resources: { 'zh-TW': { translation: zhTW }, 'en-US': { translation: enUS } },
  lng: initialLanguage,
  fallbackLng: 'zh-TW',
  supportedLngs: ['zh-TW', 'en-US'],
  // React 會跳脫文字節點；不要讓 i18next 再跳一次（路徑裡的反斜線、引號會變成 &#x2F;）
  interpolation: { escapeValue: false },
  returnNull: false,
});

/** 切換語言：i18next、<html lang>、記住到下次。 */
export function setLanguage(lang: Language): void {
  if (i18n.language !== lang) void i18n.changeLanguage(lang);
  document.documentElement.lang = lang === 'zh-TW' ? 'zh-Hant-TW' : 'en-US';
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* 沒有 localStorage：只是下次不記得 */
  }
}

/** 給非 React 程式用的翻譯函式（目前語言）。 */
export const tr: Translate = (key, vars) => i18n.t(key, vars as Record<string, unknown>) as string;

export default i18n;
