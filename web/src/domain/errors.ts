/**
 * 後端錯誤句子的「說明」（S14）：服務層的英文原句（CONTRACT-layering L3）永遠不改，
 * 畫面顯示說明（zh-TW 是中文，en-US 是較好懂的英文），原句放在提示（title）裡。
 * 先比完整句子，再比前綴；頁面自己組的複合句（「匯出失敗：{檔}：{原因}」）只說明全形冒號後面那段。
 * 認不得的句子原樣顯示（plan §2：v2 不翻後端句子；中文原句本來就看得懂）。
 */
import { zh, type Translate } from './text';

/** 完整句子 → 語言檔的鍵。 */
const EXACT: Record<string, string> = {
  'path is required': 'explain.pathRequired',
  'unsupported photo format (JPEG/PNG/TIFF/HEIC)': 'explain.unsupportedFormat',
  'unknown image_id': 'explain.unknownImage',
  'strength must be a number in 0..200': 'explain.strengthNumber',
  'body must be JSON': 'explain.bodyJson',
};

/** 前綴 → 語言檔的鍵（{{x}} 是前綴後面那段）。順序重要：較長的前綴先比。 */
const PREFIX: Array<[string, string]> = [
  ['photo not found: ', 'explain.photoNotFound'],
  ['unknown or unsupported preset ', 'explain.unknownOrUnsupportedPreset'],
  ['unknown preset ', 'explain.unknownPreset'],
  ['strength must be within 0..200, got ', 'explain.strengthRange'],
  ['unknown slider key ', 'explain.unknownSlider'],
  ['request refused: ', 'explain.refused'],
];

/** 給測試看的對照（舊 logic.js 也匯出這兩個）。 */
export const EXPLAIN_EXACT: Record<string, string> = Object.fromEntries(Object.entries(EXACT).map(([k, v]) => [k, zh(v)]));
export const EXPLAIN_PREFIX = PREFIX;

function explainOne(m: string, t: Translate): string | null {
  if (Object.prototype.hasOwnProperty.call(EXACT, m)) return t(EXACT[m]);
  for (const [prefix, key] of PREFIX) if (m.startsWith(prefix)) return t(key, { x: m.slice(prefix.length) });
  return null;
}

/** 整句，或複合句全形冒號後面那段；其他原樣。 */
export function explain(msg: unknown, t: Translate = zh): string {
  const m = String(msg == null ? '' : msg);
  const whole = explainOne(m, t);
  if (whole !== null) return whole;
  for (let i = m.indexOf('：'); i >= 0; i = m.indexOf('：', i + 1)) {
    const tail = explainOne(m.slice(i + 1), t);
    if (tail !== null) return m.slice(0, i + 1) + tail;
  }
  return m;
}
