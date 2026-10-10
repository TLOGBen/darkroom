/**
 * 元件用的翻譯函式：包 react-i18next 的 `t` 成 domain 的 `Translate` 型別（`(key, vars) => string`），
 * 這樣同一個 `t` 可以直接寫在 JSX 裡，也可以傳給 domain 的句子函式（sliderTooltip、exportSummary…）。
 * 語言切換時 react-i18next 會讓用到它的元件重畫。
 */
import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import type { Translate } from '../domain/text';

export function useT(): Translate {
  const { t } = useTranslation();
  return useCallback<Translate>((key, vars) => t(key, vars as never) as unknown as string, [t]);
}
