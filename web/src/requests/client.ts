/**
 * fetch 層的唯一出口：所有 /api/* 請求都從這裡發（plan-v2 §2 requests/client.ts）。
 *
 * 資料怎麼流：元件／hooks → requests/<領域>.ts → 這裡的 `api()` → middlewares（本機標頭、錯誤正規化）→ fetch。
 * 後端回應有兩種：JSON（大部分）與 JPEG（預覽、縮圖，回應標頭帶 X-Render-Ms、X-Edited、X-Edit）。
 * 錯誤一律是 `ApiError`，message 保持後端原句（v2 不翻後端句子，畫面用 domain/errors 的 explain 補說明）。
 */
import { localHeaders, networkError, normalizeError } from '../middlewares';

export { ApiError, isAbort } from '../middlewares';

export type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

export interface ApiOptions {
  signal?: AbortSignal;
  /** 頁面關閉時仍送得出去（自動存檔在 beforeunload 用） */
  keepalive?: boolean;
}

/** 發請求，回原始 Response（2xx 才回；否則丟 ApiError）。 */
export async function api(method: Method, url: string, json?: unknown, opts: ApiOptions = {}): Promise<Response> {
  let r: Response;
  try {
    r = await fetch(url, localHeaders({ method, json, signal: opts.signal, keepalive: opts.keepalive }));
  } catch (e) {
    throw networkError(e);
  }
  if (!r.ok) throw await normalizeError(r);
  return r;
}

/** 發請求並解析 JSON。 */
export async function apiJson<T>(method: Method, url: string, json?: unknown, opts?: ApiOptions): Promise<T> {
  return (await (await api(method, url, json, opts)).json()) as T;
}

/** 組 query string（值為 undefined／null 的略過）。 */
export function withQuery(url: string, q: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null) p.set(k, String(v));
  const s = p.toString();
  return s ? `${url}?${s}` : url;
}
