/**
 * localStorage／sessionStorage 的安全讀寫（沒有業務知識）。
 * 私密視窗或被封鎖時存取會丟例外；這些偏好都是「有更好、沒有也照常」，所以一律吞掉錯誤、回預設。
 * 鍵沿用舊版（`darkroom.<名稱>`，值是 JSON），升級後使用者的選擇還在。
 */
export function loadPref<T>(name: string, fallback: T): T {
  try {
    const v = localStorage.getItem('darkroom.' + name);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function savePref(name: string, value: unknown): void {
  try {
    localStorage.setItem('darkroom.' + name, JSON.stringify(value));
  } catch {
    /* 偏好是選配的 */
  }
}

export function loadRaw(storage: 'local' | 'session', key: string): string | null {
  try {
    return (storage === 'local' ? localStorage : sessionStorage).getItem(key);
  } catch {
    return null;
  }
}

export function saveRaw(storage: 'local' | 'session', key: string, value: string): void {
  try {
    (storage === 'local' ? localStorage : sessionStorage).setItem(key, value);
  } catch {
    /* 選配 */
  }
}
