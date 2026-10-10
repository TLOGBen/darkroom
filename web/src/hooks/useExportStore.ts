/**
 * 匯出 context 的狀態（zustand）：匯出對話框開給誰（開著的這張／縮圖格選取的）、是否匯出中，以及實際匯出。
 *
 * 從舊 app.js 的 openExportDialog／runExport／exportPhoto／exportSelected 搬過來（S2 E15、E15a、E29、S13 a）：
 *   - 開著的這張：照畫面上的參數匯出（不是只送路徑），所以存檔失敗也不會變成匯出存好的或原圖（E15a）；
 *     匯出前先把存檔送出（S11），讓照片庫盡量跟匯出的一致。
 *   - 縮圖格選取的：只送路徑，伺服器用每張自己存好的編輯（E15）。
 *   - 匯出中再按一次不會重匯（S13 a）；透過 HTTP 永遠不送資料夾（XP16）。
 * 對話框的表單值在元件（components/export/ExportDialog）裡，送出時才傳 ExportSettings 進來。
 */
import { create } from 'zustand';
import { exportFailed, exportMessage, exportRequest, EXPORT_SETTINGS_KEY, type ExportSettings } from '../domain/export';
import { exportSelectedDone } from '../domain/library';
import { explain } from '../domain/errors';
import { baseName } from '../domain/text';
import { capReason } from '../domain/settings';
import * as exportReq from '../requests/exports';
import { tr } from '../i18n';
import { saveRaw } from '../utils/storage';
import { toast } from './useAppStore';
import { capabilitiesNow } from './queries';
import { useEditStore } from './useEditStore';
import { useLibraryStore } from './useLibraryStore';
import { nonZeroOverrides, strengthInEffect } from '../domain/edit';
import { normGeometry } from '../domain/geometry';

export type ExportTarget = 'photo' | 'selected';

interface ExportState {
  open: boolean;
  target: ExportTarget | null;
  busy: boolean;
  openDialog: (target: ExportTarget) => Promise<void>;
  closeDialog: () => void;
  run: (settings: ExportSettings) => Promise<void>;
}

export const useExportStore = create<ExportState>((set, get) => {
  async function exportPhoto(settings: ExportSettings): Promise<void> {
    const lib = useLibraryStore.getState();
    const img = lib.image;
    if (!img) return;
    const name = baseName(img.path);
    await lib.commitCarried();
    try {
      if (capReason(capabilitiesNow(), 'photo_library') === null) await useLibraryStore.getState().flushAll();
      const ed = useEditStore.getState().ed;
      const item = {
        image_id: img.image_id,
        preset_id: ed.presetId,
        strength: strengthInEffect(ed),
        overrides: nonZeroOverrides(ed.tweaks),
        geometry: normGeometry(ed.geometry),
      };
      const res = await exportReq.exportPhotos(exportRequest([item], settings));
      const r = res.results[0];
      toast(r.ok ? exportMessage(r, tr) : exportFailed(name, explain(r.error, tr), tr), !r.ok, r.error);
    } catch (e) {
      toast(exportFailed(name, explain((e as Error).message, tr), tr), true, (e as Error).message);
    }
  }

  async function exportSelected(settings: ExportSettings): Promise<void> {
    const lib = useLibraryStore.getState();
    const paths = lib.selectedPaths();
    if (!paths.length) return;
    await lib.flushAll();
    const lines: string[] = [];
    let ok = 0;
    let fail = 0;
    try {
      const res = await exportReq.exportPhotos(exportRequest(paths.map((p) => ({ path: p })), settings));
      ok = res.results.filter((r) => r.ok).length;
      fail += res.results.length - ok;
      for (const r of res.results)
        if (!r.ok) lines.push(tr('grid.failedLine', { name: baseName(r.source), reason: explain(r.error, tr) }));
    } catch (e) {
      fail += paths.length;
      lines.push(explain((e as Error).message, tr));
    }
    const summary = exportSelectedDone(ok, fail, tr);
    useLibraryStore.getState().setGridResult(lines.length ? { summary, lines } : null);
    toast(summary, fail > 0);
  }

  return {
    open: false,
    target: null,
    busy: false,

    async openDialog(target) {
      await useEditStore.getState().leaveCrop(true); // C22（D10）：打開匯出對話框＝完成裁切
      const lib = useLibraryStore.getState();
      if (target === 'photo' ? !lib.image : !lib.grid.sel.size) return;
      set({ open: true, target });
    },

    closeDialog: () => set({ open: false }),

    async run(settings) {
      if (get().busy) return;
      saveRaw('local', EXPORT_SETTINGS_KEY, JSON.stringify(settings)); // 下次打開用同一組設定
      set({ busy: true });
      try {
        if (get().target === 'selected') await exportSelected(settings);
        else await exportPhoto(settings);
      } finally {
        set({ busy: false, open: false });
      }
    },
  };
});
