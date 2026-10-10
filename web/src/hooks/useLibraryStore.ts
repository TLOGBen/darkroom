/**
 * 照片庫 context 的狀態（zustand）：開著的照片、同資料夾清單、這張在照片庫裡的編輯（含 Preset 快照）、
 * 自動存檔、縮圖格（資料夾、篩選、多選、角標）、複製／貼上編輯、還原成原圖／取回上一份。
 *
 * 從舊 app.js 的 openPhoto／loadEdit／scheduleSave／showGrid／pasteEdit… 搬過來，行為一樣。
 *
 * 資料怎麼流：
 *   開照片：POST /api/open → 編輯狀態「沿用」（C24：裁切不沿用）→ GET /api/folder（上一張／下一張）
 *     → GET /api/edit：有存好的編輯就經 reducer 的 restoreEdit 換上（不排存檔），沒有就保留沿用的狀態（S11 提示）。
 *     讀不到存好的編輯（C29）：這張不自動存檔，畫面上說明原因。
 *   每次編輯改變 → `scheduleSave()` → hooks/autosave 的佇列（只送最新、失敗重試一次）。
 *   縮圖格：GET /api/folder/thumbnails → 每格看得到時由元件 GET /api/thumbnail，角標資料回寫 `updateThumb`。
 */
import { create } from 'zustand';
import { carryHintVisible, editRequest, type Edit, type PresetSnapshot } from '../domain/edit';
import { explain } from '../domain/errors';
import {
  FILTERS,
  cleanPath,
  copied,
  folderOf,
  gridFilter,
  gridSelect,
  loadEditFailed,
  loadFolderFailed,
  onlyShown,
  openFailed,
  pasteConfirmWith,
  pasteDone,
  presetStatusText,
  resetConfirm,
  resetDone,
  restoreDone,
  saveAllowed,
  saveEditFailed,
  type BadgeInfo,
  type EditInfo,
  type GridFilter,
  type Photo,
  type PhotoFolder,
  type Thumbnail,
} from '../domain/library';
import { baseName } from '../domain/text';
import { capReason } from '../domain/settings';
import * as editReq from '../requests/edits';
import * as libReq from '../requests/library';
import { tr } from '../i18n';
import { loadPref, savePref } from '../utils/storage';
import { AutosaveQueue, type SaveJob } from './autosave';
import { confirmAsk, setStatus, toast } from './useAppStore';
import { capabilitiesNow } from './queries';
import { useEditStore } from './useEditStore';

export interface GridResult {
  summary: string;
  lines: string[];
}

export interface GridState {
  folder: string | null;
  items: Array<Thumbnail & { info?: BadgeInfo | null }>;
  sel: Set<number>;
  anchor: number;
  filter: GridFilter;
}

interface LibraryState {
  image: Photo | null;
  folder: PhotoFolder | null;
  /** S1：開到一半（存好的編輯還沒還原）的那次開啟的序號 */
  loading: number | null;
  /** 開照片失敗時預覽區顯示的句子（與原句） */
  openError: { text: string; original: string } | null;
  /** 這張在照片庫裡的編輯 */
  edit: Edit | null;
  snapshots: Record<string, PresetSnapshot>;
  fingerprint: string | null;
  previous: boolean;
  editStatus: string | null;
  /** C29：讀不到存好編輯的那張照片的路徑 */
  editUnreadable: string | null;
  clipboard: { edit: Edit; name: string } | null;
  gridOpen: boolean;
  grid: GridState;
  gridResult: GridResult | null;
  pasteGeometry: boolean;

  openPhoto: (path: string) => Promise<void>;
  step: (delta: number) => void;
  scheduleSave: () => void;
  flushAll: () => Promise<void>;
  loadEdit: (path: string, token?: number) => Promise<void>;
  editStatusText: () => string;
  resetOriginal: () => Promise<void>;
  restorePrevious: () => Promise<void>;
  commitCarried: () => Promise<void>;
  // 縮圖格
  showGrid: (on: boolean) => Promise<void>;
  loadGrid: (folder: string) => Promise<void>;
  setGridFilter: (f: GridFilter) => Promise<void>;
  selectCell: (i: number, mods: { ctrl?: boolean; shift?: boolean }) => void;
  updateThumb: (path: string, edited: boolean, info: BadgeInfo | null) => void;
  selectedPaths: () => string[];
  shownSet: () => Set<number>;
  copyEdit: () => void;
  pasteEdit: () => Promise<void>;
  gridResetOriginal: () => Promise<void>;
  gridRestore: () => Promise<void>;
  setPasteGeometry: (v: boolean) => void;
  setGridResult: (r: GridResult | null) => void;
  unload: () => void;
}

const capOff = (key: string) => capReason(capabilitiesNow(), key);

let openSeq = 0; // S1：最新的 openPhoto 贏；較舊的回應丟掉

export const useLibraryStore = create<LibraryState>((set, get) => {
  /** 照片庫回來的狀態：記住 Preset 快照（S2）、上一份、preset 狀態。 */
  function applyEditInfo(res: Partial<EditInfo>): void {
    const snapshots = { ...get().snapshots };
    if (res.edit && res.edit.preset) snapshots[res.edit.preset.id] = res.edit.preset;
    set({
      edit: res.edit ?? null,
      fingerprint: res.fingerprint || null,
      previous: !!res.previous,
      editStatus: res.preset_status || null,
      snapshots,
    });
  }

  /** 存好的編輯回來：經 reducer，不排存檔。 */
  function restore(res: EditInfo): void {
    applyEditInfo(res);
    if (!res.edit) return;
    void useEditStore.getState().dispatch({ type: 'restoreEdit', edit: res.edit }, { restore: true });
  }

  const queue = new AutosaveQueue({
    async send(job: SaveJob, keepalive: boolean) {
      if (job.req.method === 'PASTE') {
        // S2：記得的快照原樣寫回（PL8），再讀一次
        const r = await editReq.pasteEdit(job.req.body, { keepalive });
        const bad = r.results.find((x) => !x.ok);
        if (bad) throw new Error(bad.error);
        return editReq.getEdit(job.path);
      }
      // keepalive：beforeunload 送出的存檔在頁面關掉後仍會送到（seal F3）
      return editReq.putEdit(job.req.body, { keepalive });
    },
    onSaved(path, info) {
      if (get().image?.path === path) applyEditInfo(info);
    },
    onError(message) {
      toast(saveEditFailed(explain(message, tr), tr), true, message);
    },
  });

  function failOpen(path: string, reason: string): void {
    // S13 (i)：舊的照片拿掉，原因看得懂
    useEditStore.getState().clearPreview();
    set({
      image: null,
      folder: null,
      loading: null,
      edit: null,
      fingerprint: null,
      previous: false,
      editStatus: null,
      openError: { text: openFailed(baseName(path), explain(reason, tr), tr), original: reason },
    });
    setStatus((t) => t('status.previewIdle'));
    toast(openFailed(baseName(path), explain(reason, tr), tr), true, reason);
  }

  /** S10：一個一個送（依順序），結果寫進縮圖格的結果面板。 */
  async function gridEach(
    run: (p: string) => Promise<unknown>,
    targets: string[],
    summary: (ok: number, failed: number) => string,
    edited: boolean,
  ): Promise<void> {
    const results: Array<{ ok: boolean; error?: string }> = [];
    for (const p of targets) {
      try {
        await run(p);
        results.push({ ok: true });
      } catch (e) {
        results.push({ ok: false, error: (e as Error).message });
      }
    }
    batchDone(summary, targets, results);
    markCells(targets, results, edited);
    const img = get().image;
    if (img && targets.includes(img.path)) await get().loadEdit(img.path);
  }

  function batchDone(
    summary: (ok: number, failed: number) => string,
    targets: string[],
    results: Array<{ ok: boolean; error?: string }>,
  ): void {
    const ok = results.filter((r) => r.ok).length;
    const lines = results
      .map((r, k) => (r.ok ? null : tr('grid.failedLine', { name: baseName(targets[k]), reason: explain(r.error, tr) })))
      .filter((x): x is string => !!x);
    const text = summary(ok, results.length - ok);
    set({ gridResult: lines.length ? { summary: text, lines } : null });
    toast(text, lines.length > 0);
  }

  function markCells(targets: string[], results: Array<{ ok: boolean }>, edited: boolean): void {
    const items = get().grid.items.map((it) => {
      const k = targets.indexOf(it.path);
      return k >= 0 && results[k]?.ok ? { ...it, edited, info: edited && it.info ? { ...it.info, status: null } : null } : it;
    });
    set({ grid: { ...get().grid, items } });
  }

  return {
    image: null,
    folder: null,
    loading: null,
    openError: null,
    edit: null,
    snapshots: {},
    fingerprint: null,
    previous: false,
    editStatus: null,
    editUnreadable: null,
    clipboard: null,
    gridOpen: false,
    grid: { folder: null, items: [], sel: new Set(), anchor: 0, filter: 'all' },
    gridResult: null,
    pasteGeometry: false,

    async openPhoto(raw) {
      const path = cleanPath(raw);
      if (!path) return;
      const token = ++openSeq; // S1：在送存檔之前拿，存檔途中的新點擊仍然是最新的
      await useEditStore.getState().leaveCrop(true); // C22（D10）：開另一張＝完成這張的裁切
      await get().flushAll(); // 上一張最後的改變先送（PL15），失敗的也不留（S13g''）
      if (token !== openSeq) return;
      setStatus((t) => t('status.loadingPhoto'), 'busy');
      let info: Omit<Photo, 'path'>;
      try {
        info = await libReq.openPhoto(path);
      } catch (e) {
        if (token === openSeq) failOpen(path, (e as Error).message);
        return;
      }
      if (token !== openSeq) return;
      // 從這裡到存好的編輯還原之前，什麼都不排存檔（S1）：狀態還在途中
      set({
        loading: token,
        image: { ...info, path },
        openError: null,
        snapshots: {},
        fingerprint: null,
        previous: false,
        editStatus: null,
        edit: null,
        editUnreadable: null, // C29：讀到這張的編輯之前，沒人知道能不能存
      });
      await useEditStore.getState().dispatch({ type: 'carry' }, { restore: true }); // C24（S11'）
      savePref('lastPath', path);
      let folder: PhotoFolder | null;
      try {
        folder = await libReq.photoFolder(info.image_id);
      } catch {
        folder = null;
      }
      if (token !== openSeq) return;
      set({ folder });
      await get().loadEdit(path, token);
      if (token !== openSeq) return;
      set({ loading: null });
      useEditStore.getState().requestPreview();
    },

    step(delta) {
      const f = get().folder;
      if (!f || f.index < 0) return;
      const i = f.index + delta;
      if (i < 0 || i >= f.files.length) return; // 第一張／最後一張：什麼都不做
      void get().openPhoto(f.files[i].path);
    },

    scheduleSave() {
      const img = get().image;
      if (!img || get().loading) return;
      if (!saveAllowed(get().editUnreadable, img.path)) return; // C29：永遠不蓋掉讀不到的編輯
      if (capOff('photo_library') !== null) return; // S2 E23：照片庫關閉——什麼都不存
      const ed = useEditStore.getState().ed;
      queue.schedule({ path: img.path, req: editRequest(ed, img.path, get().snapshots, get().fingerprint) });
    },

    async flushAll() {
      await queue.flush();
      await queue.flushRetries(); // S13g''：失敗的存檔不會晚到、蓋掉之後的動作
    },

    async loadEdit(path, token) {
      if (capOff('photo_library') !== null) {
        applyEditInfo({ edit: null, preset_status: null });
        return;
      }
      let res: EditInfo;
      try {
        res = await editReq.getEdit(path);
      } catch (e) {
        if (get().image?.path !== path) return;
        set({ editUnreadable: path }); // C29：讀成功之前這張不自動存檔
        applyEditInfo({ edit: null, preset_status: null });
        toast(loadEditFailed(explain((e as Error).message, tr), tr), true, (e as Error).message);
        return;
      }
      if (get().image?.path !== path || (token !== undefined && token !== openSeq)) return; // S1
      if (get().editUnreadable === path) set({ editUnreadable: null }); // 重讀成功：可以恢復存檔
      restore(res);
    },

    editStatusText() {
      const img = get().image;
      const unreadable = !!img && !saveAllowed(get().editUnreadable, img.path); // C29：畫面上要說
      return unreadable ? tr('editor.editUnreadable') : presetStatusText(get().editStatus, tr);
    },

    async resetOriginal() {
      // 編輯器：一步可復原；照片庫留著被清掉的那份
      if (!get().image) return;
      const es = useEditStore.getState();
      await es.leaveCrop(true);
      const before = useEditStore.getState().ed;
      await useEditStore.getState().dispatch({ type: 'resetToOriginal' });
      if (useEditStore.getState().ed !== before) toast(tr('editor.resetToast'));
    },

    async restorePrevious() {
      const img = get().image;
      if (!img || get().edit || !get().previous) return;
      const path = img.path;
      await get().flushAll();
      // 重試的存檔剛給了這張一份編輯、或正在開另一張：沒有東西可取回
      if (get().image?.path !== path || get().loading || get().edit) return;
      try {
        const res = await editReq.restoreEdit(path);
        if (get().image?.path === path) {
          restore(res);
          useEditStore.getState().requestPreview();
          toast(tr('editor.restoreToast'));
        }
      } catch (e) {
        toast(explain((e as Error).message, tr), true, (e as Error).message);
      }
    },

    async commitCarried() {
      // S11：沿用來的狀態在匯出前先變成這張的編輯
      if (!get().image || get().edit || !carryHintVisible(useEditStore.getState().ed, true, false)) return;
      get().scheduleSave();
      await queue.flush();
    },

    // ---- 縮圖格 ---------------------------------------------------------------------------------------------------
    async showGrid(on) {
      if (on) await useEditStore.getState().leaveCrop(true); // C22（D10）：打開縮圖格＝完成裁切
      set({ gridOpen: on });
      if (!on) return;
      if (get().grid.folder !== null) return; // S13 (f)：使用者自己載入的資料夾與選取都留著
      const img = get().image;
      const folder = img ? folderOf(img.path) : loadPref<string>('gridPath', '');
      if (folder) await get().loadGrid(folder);
    },

    async loadGrid(raw) {
      const folder = cleanPath(raw);
      if (!folder) return;
      let res: { folder: string; items: Thumbnail[] };
      try {
        res = await libReq.folderThumbnails(folder);
      } catch (e) {
        toast(loadFolderFailed(explain((e as Error).message, tr), tr), true, (e as Error).message);
        return;
      }
      const g = get().grid;
      const keep = g.folder === res.folder; // S9：重讀同一個資料夾時保留篩選與選取
      const old = new Map(g.items.map((it) => [it.path, it]));
      savePref('gridPath', res.folder);
      set({
        grid: {
          folder: res.folder,
          // 已經載過的縮圖的角標資料保留（清單本身不帶 X-Edit）
          items: res.items.map((it) => ({ ...it, info: old.get(it.path)?.info ?? null })),
          sel: keep ? g.sel : new Set(),
          anchor: keep ? g.anchor : 0,
          filter: g.filter || 'all',
        },
      });
      set({ grid: { ...get().grid, sel: onlyShown(get().grid.sel, get().shownSet()) } });
    },

    async setGridFilter(filter) {
      if (!(FILTERS as readonly string[]).includes(filter)) return;
      set({ grid: { ...get().grid, filter } });
      // S9：重讀清單（指紋在背景陸續算好），再依篩選顯示
      if (get().grid.folder) await get().loadGrid(get().grid.folder as string);
      else set({ grid: { ...get().grid, sel: onlyShown(get().grid.sel, get().shownSet()) } });
    },

    shownSet() {
      const { shown } = gridFilter(get().grid.items, get().grid.filter);
      return new Set(shown.map(([i]) => i));
    },

    selectCell(i, mods) {
      const g = get().grid;
      const r = gridSelect(g.sel, i, mods, g.anchor);
      set({ grid: { ...g, sel: onlyShown(r.sel, get().shownSet()), anchor: r.anchor } }); // S9：只在看得到的裡面選
    },

    updateThumb(path, edited, info) {
      const items = get().grid.items.map((it) => (it.path === path ? { ...it, edited, info } : it));
      set({ grid: { ...get().grid, items } });
    },

    selectedPaths() {
      const g = get().grid;
      return [...g.sel].sort((a, b) => a - b).map((i) => g.items[i]?.path).filter((p): p is string => !!p);
    },

    copyEdit() {
      const { edit, image } = get();
      if (!edit || !image) return;
      const clipboard = { edit, name: baseName(image.path) };
      set({ clipboard });
      toast(copied(clipboard.name, tr));
    },

    async pasteEdit() {
      const targets = get().selectedPaths();
      const clip = get().clipboard;
      if (!clip || !targets.length) return;
      await get().flushAll(); // S13 (h)：開著那張的存檔不會跟貼上搶
      const withGeometry = get().pasteGeometry; // C26：預設不勾、不記住
      if (!(await confirmAsk({ title: pasteConfirmWith(clip.name, targets.length, withGeometry, tr), confirmLabel: tr('grid.pasteEdit') })))
        return;
      let res: editReq.PasteResult;
      try {
        res = await editReq.pasteEdit({ targets, edit: clip.edit, with_geometry: withGeometry });
      } catch (e) {
        toast(explain((e as Error).message, tr), true, (e as Error).message);
        return;
      }
      batchDone((ok, failed) => pasteDone(ok, failed, tr), targets, res.results);
      markCells(targets, res.results, true);
      const img = get().image;
      if (img && targets.includes(img.path)) await get().loadEdit(img.path);
    },

    async gridResetOriginal() {
      const targets = get().selectedPaths();
      if (!targets.length) return;
      await get().flushAll();
      if (!(await confirmAsk({ title: resetConfirm(targets.length, tr), confirmLabel: tr('grid.resetOriginal'), danger: true }))) return;
      await gridEach(editReq.clearEdit, targets, (ok, f) => resetDone(ok, f, tr), false);
    },

    async gridRestore() {
      const targets = get().selectedPaths();
      if (!targets.length) return;
      await get().flushAll();
      await gridEach(editReq.restoreEdit, targets, (ok, f) => restoreDone(ok, f, tr), true);
    },

    setPasteGeometry: (pasteGeometry) => set({ pasteGeometry }),
    setGridResult: (gridResult) => set({ gridResult }),

    unload() {
      if (queue.dirty) queue.unload();
    },
  };
});

