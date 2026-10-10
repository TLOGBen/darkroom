/**
 * 編輯 context 的 HTTP 請求：滑桿表、預覽（JPEG）、照片庫裡一張照片的編輯（讀、寫、清、貼、取回、存成 preset）。
 * /api/sliders 歸在編輯（滑桿是編輯的詞彙，ADR-0005）。
 * 編輯以照片內容的指紋存在 data_dir；照片路徑只讀不寫（PLP2），body 不能帶 data_dir。
 */
import type { Edit, EditBody, Overrides, SliderTable } from '../domain/edit';
import type { Geometry } from '../domain/geometry';
import type { EditInfo } from '../domain/library';
import { api, apiJson, withQuery, type ApiOptions } from './client';

export const sliderTable = () => apiJson<SliderTable>('GET', '/api/sliders');

/** POST /api/preview 的內容：geometry 一定送（null＝不套）；frame＝裁切模式看的整個轉正畫面。 */
export interface PreviewBody {
  image_id: string;
  preset_id: string | null;
  strength: number;
  overrides: Overrides;
  geometry: Geometry | null;
  frame?: boolean;
}

export interface PreviewResult {
  blob: Blob;
  /** 後端算圖毫秒（X-Render-Ms） */
  renderMs: number;
}

export async function preview(body: PreviewBody, opts?: ApiOptions): Promise<PreviewResult> {
  const r = await api('POST', '/api/preview', body, opts);
  return { renderMs: Number(r.headers.get('X-Render-Ms') || 0), blob: await r.blob() };
}

export const getEdit = (path: string) => apiJson<EditInfo>('GET', withQuery('/api/edit', { path }));
export const putEdit = (body: EditBody, opts?: ApiOptions) => apiJson<EditInfo>('PUT', '/api/edit', body, opts);
export const clearEdit = (path: string) => apiJson<EditInfo>('DELETE', withQuery('/api/edit', { path }));
export const restoreEdit = (path: string) => apiJson<EditInfo>('POST', '/api/edit/restore', { path });

export interface PasteResult {
  results: Array<{ ok: boolean; target?: string; error?: string }>;
}
export const pasteEdit = (
  body: { targets: string[]; edit: Edit; with_geometry: boolean },
  opts?: ApiOptions,
) => apiJson<PasteResult>('POST', '/api/edit/paste', body, opts);

export const saveEditAsPreset = (path: string, name: string, group: string) =>
  apiJson<{ id: string; name: string; group: string }>('POST', '/api/edit/save-preset', { path, name, group });
