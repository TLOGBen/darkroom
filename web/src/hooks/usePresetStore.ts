/**
 * Preset 庫 context 的 UI 狀態與動作（zustand）：搜尋字、展開的資料夾、鍵盤焦點列、匯入／下載的結果面板，
 * 以及最愛、改名、搬群組、建群組、群組改名、匯入、下載 .xmp、存成 preset。
 *
 * 從舊 app.js 的 libraryCall／presetMenu／groupMenu／importFiles／downloadPresets／savePreset 搬過來（K19、S2 E16／E20／E30）。
 * 列表本身是伺服器資料（hooks/queries 的 usePresets…）；寫入成功後 `invalidatePresetLibrary()` 重讀。
 * 寫入只動 preset 庫的索引、import/、user/；買來的 .xmp 永遠不變。
 */
import { create } from 'zustand';
import {
  USER_GROUP,
  downloadReport,
  downloadTooMany,
  groupCreated,
  groupPresetIds,
  idBatches,
  importReport,
  presetSaved,
  saveBody,
  uploadBatches,
  PRESET_IDS_MAX,
  type Preset,
  type PresetFile,
} from '../domain/preset';
import { canSavePreset, nonZeroOverrides, strengthInEffect } from '../domain/edit';
import { explain } from '../domain/errors';
import * as presetReq from '../requests/presets';
import * as editReq from '../requests/edits';
import { tr } from '../i18n';
import { readBase64, saveBase64, sleep } from '../utils/files';
import { loadPref, savePref } from '../utils/storage';
import { ask, toast } from './useAppStore';
import { invalidatePresetLibrary, presetsById, queryClient, keys } from './queries';
import { useEditStore } from './useEditStore';
import { useLibraryStore } from './useLibraryStore';

/** 最愛資料夾的鍵（不會跟群組名撞）。 */
export const FAV_KEY = '\u0001fav';

export interface ResultPanel {
  summary: string;
  lines: Array<{ ok: boolean; text: string }>;
}

interface PresetUiState {
  search: string;
  openFolders: Record<string, boolean>;
  focusKey: string | null;
  result: ResultPanel | null;
  setSearch: (s: string) => void;
  setOpen: (key: string, open: boolean) => void;
  setFocusKey: (k: string | null) => void;
  setResult: (r: ResultPanel | null) => void;
  toggleFavorite: (p: Preset) => Promise<void>;
  rename: (p: Preset) => Promise<void>;
  move: (p: Preset) => Promise<void>;
  newGroup: (base: string) => Promise<void>;
  renameGroup: (path: string) => Promise<void>;
  downloadPresets: (ids: string[]) => Promise<void>;
  downloadGroup: (path: string) => Promise<void>;
  importFiles: (files: File[]) => Promise<void>;
  savePreset: () => Promise<void>;
}

/** 呼叫一個 preset 庫的寫入；成功後重讀列表，失敗 toast 原句。 */
async function libraryCall<T>(call: () => Promise<T>, done?: (r: T) => string): Promise<T | null> {
  try {
    const res = await call();
    await invalidatePresetLibrary();
    if (done) toast(done(res));
    return res;
  } catch (e) {
    toast(explain((e as Error).message, tr), true, (e as Error).message);
    return null;
  }
}

export const usePresetStore = create<PresetUiState>((set, get) => ({
  search: '',
  openFolders: { [FAV_KEY]: true, ...loadPref<Record<string, boolean>>('openFolders', {}) },
  focusKey: null,
  result: null,

  setSearch: (search) => set({ search }),
  setOpen(key, open) {
    const openFolders = { ...get().openFolders, [key]: open };
    set({ openFolders });
    savePref('openFolders', openFolders);
  },
  setFocusKey: (focusKey) => set({ focusKey }),
  setResult: (result) => set({ result }),

  toggleFavorite: async (p) => {
    await libraryCall(() => presetReq.setFavorite(p.id, !p.favorite));
  },

  async rename(p) {
    const n = await ask({ title: tr('presets.prompt.rename'), initial: p.name, confirmLabel: tr('presets.menu.rename').replace('…', '') });
    if (n !== null) await libraryCall(() => presetReq.renamePreset(p.id, n));
  },

  async move(p) {
    const g = await ask({ title: tr('presets.prompt.move'), initial: p.group, confirmLabel: tr('presets.menu.move').replace('…', '') });
    if (g !== null) await libraryCall(() => presetReq.movePreset(p.id, g));
  },

  async newGroup(base) {
    const g = await ask({ title: tr('presets.prompt.newGroup'), initial: base ? base + ' - ' : '', confirmLabel: tr('presets.newGroup') });
    if (g !== null) await libraryCall(() => presetReq.createGroup(g), (r) => groupCreated(r.group, tr));
  },

  async renameGroup(path) {
    const n = await ask({ title: tr('presets.prompt.renameGroup'), initial: path, confirmLabel: tr('presets.menu.renameGroup').replace('…', '') });
    if (n !== null) await libraryCall(() => presetReq.renameGroup(path, n));
  },

  async downloadPresets(ids) {
    // S2 E16／E30：頁面自己下載（每個請求 1～500 個 id），伺服器不替網頁寫檔；一個接一個下載，失敗列在結果面板
    if (!ids.length) return;
    if (ids.length > PRESET_IDS_MAX) {
      toast(downloadTooMany(ids.length, tr), true);
      return;
    }
    const files: PresetFile[] = [];
    try {
      for (const batch of idBatches(ids)) files.push(...(await presetReq.presetFiles(batch)).files);
    } catch (e) {
      toast(explain((e as Error).message, tr), true, (e as Error).message);
    }
    if (!files.length) return;
    for (const f of files) {
      if (!f.ok || !f.file_name || f.data_base64 === undefined) continue;
      saveBase64(f.file_name, f.data_base64);
      await sleep(120); // 一個接一個：瀏覽器才會保留每個下載
    }
    const rep = downloadReport(files, tr);
    set({ result: { summary: rep.summary, lines: files.map((f, i) => ({ ok: f.ok, text: explain(rep.lines[i], tr) })) } });
    toast(rep.summary, files.some((f) => !f.ok));
  },

  async downloadGroup(path) {
    const presets = queryClient.getQueryData<Preset[]>(keys.presets) ?? [];
    await get().downloadPresets(groupPresetIds(presets, path));
  },

  async importFiles(fileList) {
    // KP4：只傳使用者挑的位元組，永遠不送路徑
    const files = [];
    for (const f of fileList) files.push({ name: f.name, data_base64: await readBase64(f) });
    if (!files.length) return;
    const results: Array<{ ok: boolean; id?: string; error?: string }> = [];
    try {
      for (const batch of uploadBatches(files)) results.push(...(await presetReq.importPresets(batch)).results);
    } catch (e) {
      toast(explain((e as Error).message, tr), true, (e as Error).message);
    }
    if (!results.length) return;
    const rep = importReport(results, tr);
    set({ result: { summary: rep.summary, lines: results.map((r, i) => ({ ok: r.ok, text: rep.lines[i] })) } });
    toast(rep.summary, results.some((r) => !r.ok));
    await invalidatePresetLibrary();
  },

  async savePreset() {
    // 讀編輯、從不改它：不 dispatch、不記復原步驟（K19）
    const ed = useEditStore.getState().ed;
    if (!canSavePreset(ed)) return;
    const byId = presetsById();
    const name = await ask({
      title: tr('presets.prompt.saveName'),
      initial: ed.presetId !== null && byId[ed.presetId] ? byId[ed.presetId].name : '',
      confirmLabel: tr('editor.savePreset'),
    });
    if (name === null) return;
    // 群組名是資料（後端預設也是這個名字），不隨介面語言翻譯
    const group = await ask({ title: tr('presets.prompt.saveGroup'), initial: USER_GROUP, confirmLabel: tr('editor.savePreset') });
    if (group === null) return;
    const lib = useLibraryStore.getState();
    await lib.flushAll(); // S13g'''：不會有失敗的存檔晚到
    const now = useLibraryStore.getState();
    if (now.image && now.edit) {
      // PLP6：照片庫的編輯（含快照）是來源。只是沿用、沒改過的照片還沒有編輯：走下面的 preset 庫流程（seal F4）
      try {
        const r = await editReq.saveEditAsPreset(now.image.path, name, group || USER_GROUP);
        await invalidatePresetLibrary();
        toast(presetSaved(r.name, tr));
      } catch (e) {
        toast(explain((e as Error).message, tr), true, (e as Error).message);
      }
      return;
    }
    const cur = useEditStore.getState().ed;
    const req = { preset_id: cur.presetId, strength: strengthInEffect(cur), overrides: nonZeroOverrides(cur.tweaks) };
    await libraryCall(() => presetReq.saveUserPreset(saveBody(req, name, group || USER_GROUP)), (r) => presetSaved(r.name, tr));
  },
}));
