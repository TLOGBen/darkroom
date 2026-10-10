/**
 * vitest 共用設定：jest-dom 的 matcher（toBeInTheDocument…）、每個測試後清掉畫面。
 * jsdom 沒有 matchMedia／ResizeObserver／IntersectionObserver，補最小的假物件（元件只需要「有這個東西」）。
 */
import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => cleanup());

if (typeof window !== 'undefined') {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// 測試一律用 zh-TW（jsdom 的 navigator.language 是 en-US）：釘住的句子是中文原句
import i18n from '../i18n';
await i18n.changeLanguage('zh-TW');
