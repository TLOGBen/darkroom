/**
 * 檔案與下載的小工具（沒有業務知識）：讀使用者挑的檔成 base64、把位元組交給瀏覽器下載、讀文字檔。
 * darkroom 透過 HTTP 永遠不送路徑、伺服器也不替網頁寫檔，所以檔案一律在瀏覽器這邊轉成位元組或下載。
 */

/** File → base64（不含 data: 前綴）。 */
export function readBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).replace(/^data:[^,]*,/, ''));
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}

/** File → 文字。 */
export function readText(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = () => reject(fr.error);
    fr.readAsText(file);
  });
}

/** Blob → 觸發瀏覽器下載（檔名由呼叫端決定）。 */
export function saveBlob(fileName: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/** base64 → 下載。 */
export function saveBase64(fileName: string, base64: string): void {
  const bin = atob(base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  saveBlob(fileName, new Blob([bytes], { type: 'application/octet-stream' }));
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
