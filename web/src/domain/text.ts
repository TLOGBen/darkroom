/**
 * 前端領域層共用的「文字」工具：翻譯函式型別、預設的 zh-TW 翻譯、深拷貝／比較。
 *
 * 為什麼 domain 需要翻譯：舊 logic.js 的純函式直接回中文句子（例如滑桿提示「preset × 150% = …」），
 * 而且這些句子被測試逐字釘住。v2 所有給人看的字都要走 i18n，所以這裡的作法是：
 *   - 句子本身放在 `i18n/locales/*.json`（zh-TW 與 en-US 同一組鍵）；
 *   - 會產生句子的純函式多收一個 `t: Translate` 參數，預設值是本檔的 `zh`（直接讀 zh-TW.json）；
 *   - 元件呼叫時傳 i18next 的 `t`，畫面就跟著語言切換；單元測試不傳，得到的就是舊版的中文原句。
 * `zh` 的插值語法跟 i18next 預設一樣（`{{name}}`），所以兩邊讀同一份 JSON 會得到同一句話。
 */
import zhTW from '../i18n/locales/zh-TW.json';

/** 翻譯函式：鍵 → 句子；`vars` 代入 `{{name}}`。i18next 的 `t` 與本檔的 `zh` 都符合這個形狀。 */
export type Translate = (key: string, vars?: Record<string, unknown>) => string;

type Tree = { [k: string]: string | Tree };

function lookup(tree: Tree, key: string): string | undefined {
  let node: string | Tree | undefined = tree;
  for (const part of key.split('.')) {
    if (node === undefined || typeof node === 'string') return undefined;
    node = node[part];
  }
  return typeof node === 'string' ? node : undefined;
}

/** `{{name}}` 插值（跟 i18next 預設相同；不做 HTML 跳脫，React 本來就會跳脫文字節點）。 */
export function interpolate(template: string, vars?: Record<string, unknown>): string {
  if (!vars) return template;
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (m, name: string) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : m,
  );
}

/** 預設翻譯：zh-TW。找不到鍵就回鍵本身（跟 i18next 的預設行為一致，方便一眼看出漏翻）。 */
export const zh: Translate = (key, vars) => interpolate(lookup(zhTW as Tree, key) ?? key, vars);

/** JSON 深拷貝：編輯狀態只含 JSON 值（數字、字串、null、陣列、物件），用 JSON 來回最簡單也最可靠。 */
export const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** 兩個 JSON 值是否相同（鍵順序相同時）；舊 logic.js 的 `same`。 */
export const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

/** 四捨五入到 d 位小數。 */
export const round = (v: number, d: number): number => {
  const k = Math.pow(10, d);
  return Math.round(v * k) / k;
};

/** 路徑的檔名部分（Windows 與 POSIX 分隔符都認）。 */
export const baseName = (p: string | null | undefined): string => String(p ?? '').split(/[\\/]/).pop() ?? '';
