/**
 * Preset 庫 context 的 HTTP 請求（後端 darkroom_app/server.py 的 /api/presets*、/api/preset-library/*）。
 * 寫入的請求只動 preset 庫的索引（library.json）、import/ 與 user/；透過 HTTP 永遠不送路徑（KP4：匯入只傳位元組）。
 */
import type { Preset, PresetFile, PresetFlags, PresetGroups, SaveBody, UploadFile } from '../domain/preset';
import type { PresetDetailLike } from '../domain/edit';
import { apiJson } from './client';

export interface PresetDetail extends PresetDetailLike {
  id: string;
  name: string;
  group: string;
  skipped?: string[];
  level?: 'major' | 'minor' | null;
}

export const listPresets = () => apiJson<Preset[]>('GET', '/api/presets');
export const presetFlags = () => apiJson<PresetFlags>('GET', '/api/preset_flags');
export const presetGroups = () => apiJson<PresetGroups>('GET', '/api/preset-library/groups');
export const presetDetail = (id: string) => apiJson<PresetDetail>('GET', '/api/presets/' + encodeURIComponent(id));

export const setFavorite = (presetId: string, favorite: boolean) =>
  apiJson<unknown>('POST', '/api/preset-library/favorite', { preset_id: presetId, favorite });
export const renamePreset = (presetId: string, name: string) =>
  apiJson<unknown>('POST', '/api/preset-library/rename', { preset_id: presetId, name });
export const movePreset = (presetId: string, group: string) =>
  apiJson<unknown>('POST', '/api/preset-library/move', { preset_id: presetId, group });
export const createGroup = (group: string) =>
  apiJson<{ group: string }>('POST', '/api/preset-library/groups/create', { group });
export const renameGroup = (group: string, newName: string) =>
  apiJson<unknown>('POST', '/api/preset-library/groups/rename', { group, new_name: newName });
export const importPresets = (files: UploadFile[]) =>
  apiJson<{ results: Array<{ ok: boolean; id?: string; error?: string }> }>('POST', '/api/preset-library/import', { files });
export const saveUserPreset = (body: SaveBody) =>
  apiJson<{ id: string; name: string; group: string }>('POST', '/api/preset-library/save', body);
export const presetFiles = (ids: string[]) =>
  apiJson<{ files: PresetFile[] }>('POST', '/api/preset-library/files', { preset_ids: ids });
