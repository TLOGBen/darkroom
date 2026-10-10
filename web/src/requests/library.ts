/**
 * 照片庫 context 的 HTTP 請求：開照片、同資料夾清單、縮圖格清單、單張縮圖（JPEG＋角標標頭）。
 * 這幾個 GET 讀照片路徑，後端要求 X-Darkroom: 1（middlewares 已經一律帶上）。
 */
import type { BadgeInfo, Photo, PhotoFolder, Thumbnail } from '../domain/library';
import { api, apiJson, withQuery, type ApiOptions } from './client';

export const openPhoto = (path: string, opts?: ApiOptions) =>
  apiJson<Omit<Photo, 'path'>>('POST', '/api/open', { path }, opts);

export const photoFolder = (imageId: string, opts?: ApiOptions) =>
  apiJson<PhotoFolder>('GET', withQuery('/api/folder', { image_id: imageId }), undefined, opts);

export const folderThumbnails = (folder: string) =>
  apiJson<{ folder: string; items: Thumbnail[] }>('GET', withQuery('/api/folder/thumbnails', { folder }));

export interface ThumbResult {
  blob: Blob;
  edited: boolean;
  /** S8：X-Edit 標頭（encodeURIComponent 的 JSON）；沒有或讀不懂是 null */
  info: BadgeInfo | null;
}

export async function thumbnail(path: string, opts?: ApiOptions): Promise<ThumbResult> {
  const r = await api('GET', withQuery('/api/thumbnail', { path }), undefined, opts);
  let info: BadgeInfo | null;
  try {
    const h = r.headers.get('X-Edit');
    info = h ? (JSON.parse(decodeURIComponent(h)) as BadgeInfo) : null;
  } catch {
    info = null;
  }
  return { edited: r.headers.get('X-Edited') === '1', info, blob: await r.blob() };
}
