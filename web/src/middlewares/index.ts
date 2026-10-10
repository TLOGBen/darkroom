/**
 * request 攔截器（plan-v2 §2 middlewares/）：requests/client.ts 每個請求都依序經過這裡。
 *
 * 1. `localHeaders`：每個請求都帶 `X-Darkroom: 1`；有 body 時帶 `Content-Type: application/json`。
 *    後端 darkroom_app/server.py 的 `_local_only` 規則：
 *      - 讀照片路徑的 GET（/api/folder、/api/edit、/api/folder/thumbnails、/api/thumbnail、/api/capabilities）
 *        一定要有 `X-Darkroom: 1`，否則 403「request refused: X-Darkroom header required」；
 *        別的網頁的 <img src>／<script src> 加不了這個標頭，跨站 fetch 要加就得先過 CORS preflight（後端從不回應）。
 *      - POST／PUT 的 body 一定要宣告 application/json，否則 415。
 *    所以 client 一律帶上，不用每支 request 自己記。
 * 2. `normalizeError`：非 2xx 的回應統一成 `ApiError`（後端錯誤句子原句保留在 message，kind 由狀態碼推回）。
 * 「只送最新一次」不在這層做：預覽的節流與丟棄過期回應在 hooks/useEditStore.ts。
 */

/** 後端錯誤的種類（跟 CLI／MCP 的 kind 同名；狀態碼對照見 server.py 的 STATUS）。 */
export type ErrorKind = 'invalid' | 'not_found' | 'conflict' | 'unavailable' | 'refused' | 'network' | 'unknown';

/** 統一的請求錯誤：message 是後端原句（或狀態碼），status 是 HTTP 狀態（網路錯誤為 0）。 */
export class ApiError extends Error {
  readonly kind: ErrorKind;
  readonly status: number;
  constructor(message: string, kind: ErrorKind, status: number) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
  }
}

/** 本機標頭：加在每個請求上。 */
export function localHeaders(init: RequestInit & { json?: unknown }): RequestInit {
  const headers = new Headers(init.headers);
  headers.set('X-Darkroom', '1');
  const out: RequestInit = { ...init, headers };
  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    out.body = JSON.stringify(init.json);
  }
  delete (out as { json?: unknown }).json;
  return out;
}

const KIND_BY_STATUS: Record<number, ErrorKind> = {
  400: 'invalid',
  404: 'not_found',
  409: 'conflict',
  503: 'unavailable',
  403: 'refused',
  415: 'refused',
  421: 'refused',
};

/** 非 2xx → ApiError（後端的 JSON 是 {error: "原句"}；讀不到就用狀態碼）。 */
export async function normalizeError(r: Response): Promise<ApiError> {
  let msg = String(r.status);
  try {
    const body = (await r.json()) as { error?: unknown };
    if (body && typeof body.error === 'string') msg = body.error;
  } catch {
    /* 不是 JSON：用狀態碼 */
  }
  return new ApiError(msg, KIND_BY_STATUS[r.status] ?? 'unknown', r.status);
}

/** fetch 本身丟的錯（伺服器沒開、連線中斷）→ ApiError(network)。AbortError 原樣往外丟，呼叫端自己忽略。 */
export function networkError(e: unknown): unknown {
  if (e instanceof DOMException && e.name === 'AbortError') return e;
  return new ApiError(e instanceof Error ? e.message : String(e), 'network', 0);
}


/** 是不是被呼叫端取消的請求（這種錯誤不用顯示）。 */
export const isAbort = (e: unknown): boolean => e instanceof DOMException && e.name === 'AbortError';
