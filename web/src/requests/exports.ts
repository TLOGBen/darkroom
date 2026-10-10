/**
 * 匯出 context 的 HTTP 請求：匯出（POST /api/export）與匯出預設（GET／PUT／DELETE /api/export-presets）。
 * 透過 HTTP 永遠不送資料夾（XP16）：新檔一律寫到照片旁的「darkroom 匯出」。
 */
import type { ExportFile, ExportPreset, ExportSettings } from '../domain/export';
import { apiJson, withQuery } from './client';

export interface ExportItem {
  path?: string;
  image_id?: string;
  preset_id?: string | null;
  strength?: number;
  overrides?: Record<string, number>;
  geometry?: unknown;
}

export const exportPhotos = (body: { items: ExportItem[] } & ExportSettings) =>
  apiJson<{ results: ExportFile[]; failed?: number }>('POST', '/api/export', body);

export const listExportPresets = () => apiJson<{ presets: ExportPreset[] }>('GET', '/api/export-presets');

export const saveExportPreset = (name: string, settings: ExportSettings) =>
  apiJson<{ name: string; settings: ExportSettings; previous?: ExportSettings | null }>('PUT', '/api/export-presets', {
    name,
    settings,
  });

export const deleteExportPreset = (name: string) =>
  apiJson<{ name: string; settings: ExportSettings }>('DELETE', withQuery('/api/export-presets', { name }));
