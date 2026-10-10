/**
 * 編輯 context 的狀態（zustand）：編輯狀態（preset、強度、微調、幾何＋復原歷史）、目前 preset 的細節、
 * 預覽（只送最新一次）、按住看原圖、A/B 對照、裁切模式。
 *
 * 從舊 app.js 的 dispatch／pump／showOriginal／abToggle／enterCrop… 搬過來，行為一樣，只是畫面改由 React 依狀態畫。
 *
 * 資料怎麼流：
 *   元件呼叫 `dispatch(action)` → domain/edit 的 `reduce` 產生新狀態（記一步歷史）
 *     → 畫面狀態有變：通知照片庫排自動存檔（useLibraryStore.scheduleSave；還原存好的編輯時不排）
 *     → `requestPreview()`：把目前參數放進「待送」，前一個請求回來後只送最新的那份（latest wins，不排隊）
 *     → 回來的 JPEG 先在背景解碼完才換上（不閃），舊的 object URL 釋放。
 *   preset 換了：另外讀 preset 細節（滑桿基準值、曲線、套不上的設定）；照片庫記得那個 preset 的快照時，
 *   基準值用快照（S3），不用 preset 庫現在的檔。
 *   裁切模式的草稿在 domain/geometry 的 cropSession 裡（自己的復原堆疊），完成時才變成編輯的一步 setGeometry。
 */
import { create } from 'zustand';
import {
  AB_DEFAULT_SPLIT,
  AB_STORAGE_KEY,
  abSplitFrom,
  canUndo,
  canRedo,
  detailFromSnapshot,
  initialEditor,
  nonZeroOverrides,
  reduce,
  sameEditorState,
  strengthInEffect,
  type EditorAction,
  type EditorState,
  type PresetDetailView,
  type Slider,
} from '../domain/edit';
import {
  CROP_MIN_PX,
  cropDrag,
  cropSession,
  fullGeometry,
  geometryAction,
  normGeometry,
  originalKey,
  type CropHandle,
  type CropSessionState,
  type Geometry,
  type GeometryAction,
  type GeometryLike,
} from '../domain/geometry';
import { explain } from '../domain/errors';
import { isAbort } from '../middlewares';
import * as editReq from '../requests/edits';
import * as presetReq from '../requests/presets';
import { tr } from '../i18n';
import { loadRaw, saveRaw } from '../utils/storage';
import { setStatus, toast } from './useAppStore';
import { slidersByKey } from './queries';
import { useLibraryStore } from './useLibraryStore';

export type PreviewKind = 'edit' | 'frame';

interface EditState {
  ed: EditorState;
  /** 目前 preset 的細節（滑桿基準、曲線、套不上的設定）；沒有 preset 或還沒讀到是 null */
  detail: PresetDetailView | null;
  /** 正在顯示的預覽 */
  previewUrl: string | null;
  previewKind: PreviewKind;
  /** 按住看原圖中 */
  holding: boolean;
  /** 原圖預覽（按住看原圖與 A/B 共用）與它對應的快取鍵 */
  originalUrl: string | null;
  originalFor: string | null;
  ab: { on: boolean; split: number };
  crop: CropSessionState | null;
  /** 「套不上的設定」全文是否展開 */
  skipOpen: boolean;

  dispatch: (action: EditorAction, opts?: { restore?: boolean }) => Promise<void>;
  undo: () => void;
  redo: () => void;
  selectPreset: (id: string | null) => Promise<void>;
  setStrength: (v: number, gesture?: string | null) => Promise<void>;
  setValue: (key: string, value: number, gesture?: string | null) => Promise<void>;
  endGesture: () => void;
  presetValue: (key: string) => number;
  loadPreset: (id: string | null) => Promise<void>;
  requestPreview: () => void;
  showOriginal: (on: boolean) => Promise<void>;
  /**
   * 手上的原圖預覽是不是「這一張、這個幾何」的：換照片或換幾何之後，新的原圖算好前 originalUrl 還是上一張的，
   * 不能拿來顯示（否則會先閃出上一張的原圖、還標「原圖」；原圖請求失敗就一直停在錯的照片）。
   */
  originalIsCurrent: () => boolean;
  abToggle: (on?: boolean) => Promise<void>;
  abSetSplit: (v: number) => void;
  abRefresh: () => void;
  setSkipOpen: (open: boolean) => void;
  // 裁切
  cropActive: () => boolean;
  enterCrop: () => void;
  leaveCrop: (commit: boolean) => Promise<void>;
  cropChange: (draft: GeometryLike | null, gesture?: string | null) => void;
  cropStep: (type: 'undo' | 'redo' | 'reset') => void;
  cropEndGesture: () => void;
  cropDragTo: (start: Geometry, handle: CropHandle, dx: number, dy: number, imgW: number, imgH: number, gesture: string | null) => void;
  geometryAct: (action: GeometryAction) => void;
  /** 換照片或還原原圖時清掉預覽相關的東西 */
  clearPreview: () => void;
}

/** 預覽的「只送最新一次」佇列（不放進 zustand：它不是畫面狀態）。 */
const pv = {
  pending: null as null | { body: editReq.PreviewBody; seq: number; kind: PreviewKind },
  inflight: false,
  seq: 0,
  shownSeq: 0,
};

/** 先在背景解碼完再換上，畫面不會閃一下空白。 */
function decoded(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(true);
    img.onerror = () => resolve(false);
    img.src = url;
  });
}

const photo = () => useLibraryStore.getState().image;

export const useEditStore = create<EditState>((set, get) => {
  /** 目前畫面上的預覽請求：幾何一定送（null 也送，S3 C19／C24）。 */
  function currentRequest(): editReq.PreviewBody {
    const { ed } = get();
    return {
      image_id: (photo() as NonNullable<ReturnType<typeof photo>>).image_id,
      preset_id: ed.presetId,
      strength: strengthInEffect(ed),
      overrides: nonZeroOverrides(ed.tweaks),
      geometry: normGeometry(ed.geometry),
    };
  }

  /** 裁切模式的畫面：草稿的整個轉正畫面（忽略它的框）。 */
  function frameRequest(): editReq.PreviewBody {
    const d = { ...(get().crop?.draft as Geometry), crop: null };
    return { ...currentRequest(), geometry: normGeometry(d), frame: true };
  }

  function originalRequest(): { body: editReq.PreviewBody; key: string } {
    const frame = get().cropActive();
    const img = photo() as NonNullable<ReturnType<typeof photo>>;
    const g = frame ? { ...(get().crop?.draft as Geometry), crop: null } : get().ed.geometry;
    const body: editReq.PreviewBody = {
      image_id: img.image_id,
      preset_id: null,
      strength: 100,
      overrides: {},
      geometry: normGeometry(g),
    };
    if (frame) body.frame = true;
    return { body, key: originalKey(img.image_id, g, frame) };
  }

  /** 原圖預覽（按住看原圖與對照共用）：同一張、同一個幾何只算一次。 */
  async function ensureOriginal(): Promise<boolean> {
    const img = photo();
    if (!img) return false;
    const id = img.image_id;
    const { body, key } = originalRequest();
    if (get().originalFor === key) return true;
    let res: editReq.PreviewResult;
    try {
      res = await editReq.preview(body);
    } catch (e) {
      toast(tr('status.previewFailed', { reason: explain((e as Error).message, tr) }), true, (e as Error).message);
      return false;
    }
    if (!photo() || photo()?.image_id !== id) return false;
    const old = get().originalUrl;
    const url = URL.createObjectURL(res.blob);
    await decoded(url);
    if (old) URL.revokeObjectURL(old);
    set({ originalUrl: url, originalFor: key });
    return true;
  }

  async function pump(): Promise<void> {
    pv.inflight = true;
    setStatus((t) => t('status.rendering'), 'busy');
    try {
      while (pv.pending) {
        const job = pv.pending;
        pv.pending = null;
        const t0 = performance.now();
        let res: editReq.PreviewResult;
        try {
          res = await editReq.preview(job.body);
        } catch (e) {
          if (isAbort(e)) continue;
          const msg = (e as Error).message;
          setStatus((t) => t('status.previewFailed', { reason: explain(msg, t) }), 'err', msg);
          continue;
        }
        if (job.seq < pv.shownSeq) continue;
        pv.shownSeq = job.seq;
        const url = URL.createObjectURL(res.blob);
        await decoded(url);
        const old = get().previewUrl;
        set({ previewUrl: url, previewKind: job.kind });
        if (old) URL.revokeObjectURL(old);
        get().abRefresh();
        if (!pv.pending) {
          const rt = performance.now() - t0;
          // S17：毫秒數放提示，不佔版面
          setStatus(
            (t) => t('status.updated'),
            'idle',
            (t) => t('status.updatedDetail', { backend: res.renderMs.toFixed(0), roundTrip: rt.toFixed(0) }),
          );
        }
      }
    } finally {
      pv.inflight = false;
    }
  }

  return {
    ed: initialEditor(),
    detail: null,
    previewUrl: null,
    previewKind: 'edit',
    holding: false,
    originalUrl: null,
    originalFor: null,
    ab: { on: false, split: abSplitFrom(loadRaw('session', AB_STORAGE_KEY)) },
    crop: null,
    skipOpen: false,

    async dispatch(action, opts) {
      const prev = get().ed;
      const ed = reduce(prev, action);
      if (ed === prev) return;
      set({ ed });
      if (sameEditorState(prev, ed)) return;
      if (!opts?.restore) useLibraryStore.getState().scheduleSave(); // PL15：每個改變都存；還原存好的不算改變
      get().requestPreview();
      if (prev.presetId !== ed.presetId) await get().loadPreset(ed.presetId);
    },

    // C22：裁切模式中 Ctrl+Z 只動草稿
    undo: () => (get().cropActive() ? get().cropStep('undo') : void get().dispatch({ type: 'undo' })),
    redo: () => (get().cropActive() ? get().cropStep('redo') : void get().dispatch({ type: 'redo' })),
    selectPreset: (id) => get().dispatch({ type: 'selectPreset', id }), // 強度與微調都保留（R5）
    setStrength: (value, gesture) => get().dispatch({ type: 'setStrength', value, gesture }),
    setValue: (key, value, gesture) => {
      const slider = slidersByKey()[key] as Slider;
      return get().dispatch({ type: 'setValue', slider, presetValue: get().presetValue(key), value, gesture });
    },
    endGesture: () => void get().dispatch({ type: 'endGesture' }),

    presetValue(key) {
      const s = slidersByKey()[key];
      const d = get().detail;
      return d && d.values[key] != null ? d.values[key] : (s?.default ?? 0);
    },

    async loadPreset(id) {
      set({ detail: null, skipOpen: false });
      if (id === null) return;
      let detail: presetReq.PresetDetail | null = null;
      const snapshots = useLibraryStore.getState().snapshots;
      try {
        detail = await presetReq.presetDetail(id);
      } catch (e) {
        // preset 已不在庫裡：有快照就用快照，不用說
        if (!snapshots[id]) toast(tr('presets.loadFailed', { reason: explain((e as Error).message, tr) }), true, (e as Error).message);
      }
      if (get().ed.presetId !== id) return;
      const snap = useLibraryStore.getState().snapshots[id];
      const view: PresetDetailView | null = snap
        ? detailFromSnapshot(snap, detail)
        : detail
          ? {
              id: detail.id,
              name: detail.name,
              group: detail.group,
              values: detail.values ?? {},
              curves: detail.curves ?? {},
              banner: detail.banner ?? '',
              note: detail.note ?? '',
            }
          : null;
      set({ detail: view });
    },

    requestPreview() {
      if (!photo()) return;
      const frame = get().cropActive(); // C22：裁切模式看的是整個轉正畫面
      pv.pending = { body: frame ? frameRequest() : currentRequest(), seq: ++pv.seq, kind: frame ? 'frame' : 'edit' };
      if (!pv.inflight) void pump();
    },

    async showOriginal(on) {
      if (!photo()) return;
      set({ holding: on });
      if (!on) return;
      await ensureOriginal();
    },

    originalIsCurrent() {
      const { originalUrl, originalFor } = get();
      if (!originalUrl || !originalFor || !photo()) return false;
      return originalFor === originalRequest().key;
    },

    async abToggle(on) {
      const want = on === undefined ? !get().ab.on : !!on;
      if (want && (!photo() || get().cropActive())) return; // C25：裁切中不能對照
      if (want && !(await ensureOriginal())) return;
      set({ ab: { ...get().ab, on: want } });
    },

    abSetSplit(v) {
      const split = Math.min(1, Math.max(0, v));
      saveRaw('session', AB_STORAGE_KEY, String(split));
      set({ ab: { ...get().ab, split } });
    },

    abRefresh() {
      // 換照片或換了幾何之後：原圖是另一張了
      if (!get().ab.on) return;
      if (!photo()) {
        set({ ab: { ...get().ab, on: false } });
        return;
      }
      if (get().originalFor !== originalRequest().key) void get().abToggle(true);
    },

    setSkipOpen: (skipOpen) => set({ skipOpen }),

    // ---- 裁切模式（C22–C25） --------------------------------------------------------------------------------------
    cropActive: () => !!get().crop?.active,

    enterCrop() {
      if (!photo() || get().cropActive() || useLibraryStore.getState().loading) return;
      if (get().ab.on) set({ ab: { ...get().ab, on: false } }); // C25：裁切時關掉對照，之後也不自動打開
      set({ crop: cropSession(null, { type: 'enter', geometry: get().ed.geometry }) });
      get().requestPreview();
    },

    async leaveCrop(commit) {
      // C22（D10）：只有 Esc／取消是取消；其他離開方式（另一張、縮圖格、匯出…）都是完成
      if (!get().cropActive()) return;
      const img = photo() as NonNullable<ReturnType<typeof photo>>;
      const s = cropSession(get().crop, commit ? { type: 'commit', width: img.width, height: img.height } : { type: 'cancel' });
      set({ crop: null });
      if (commit && s?.result?.changed) await get().dispatch({ type: 'setGeometry', geometry: s.result.geometry });
      else get().requestPreview();
    },

    cropChange(draft, gesture) {
      const before = get().crop?.draft;
      const next = cropSession(get().crop, { type: 'change', draft, gesture });
      set({ crop: next });
      // 拉直／旋轉／鏡像才需要新的畫面；拖框永遠不問後端（C23）
      if (frameKey(next?.draft) !== frameKey(before)) get().requestPreview();
    },

    cropStep(type) {
      const before = get().crop?.draft;
      const next = cropSession(get().crop, { type });
      set({ crop: next });
      if (frameKey(next?.draft) !== frameKey(before)) get().requestPreview();
    },

    cropEndGesture() {
      if (get().cropActive()) set({ crop: cropSession(get().crop, { type: 'endGesture' }) });
    },

    cropDragTo(start, handle, dx, dy, imgW, imgH, gesture) {
      const img = photo();
      if (!img || !get().cropActive()) return;
      const size = { width: img.width, height: img.height, minW: CROP_MIN_PX / imgW, minH: CROP_MIN_PX / imgH };
      get().cropChange(cropDrag(start, size, handle, dx, dy), gesture);
    },

    geometryAct(action) {
      // 旋轉／鏡像／直橫：裁切模式中改草稿，模式外是編輯的一步
      const img = photo();
      if (!img) return;
      if (get().cropActive()) {
        get().cropChange(geometryAction(get().crop?.draft, action, img.width, img.height));
        return;
      }
      void get().dispatch({ type: 'setGeometry', geometry: geometryAction(get().ed.geometry, action, img.width, img.height) });
    },

    clearPreview() {
      const { previewUrl, originalUrl } = get();
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      if (originalUrl) URL.revokeObjectURL(originalUrl);
      pv.pending = null;
      pv.shownSeq = pv.seq;
      set({ previewUrl: null, originalUrl: null, originalFor: null, holding: false, ab: { ...get().ab, on: false } });
    },
  };
});

/** 草稿的「畫面」部分（旋轉、鏡像、角度）：變了才需要新的整個畫面預覽。 */
const frameKey = (g: GeometryLike | null | undefined): string => {
  const f = fullGeometry(g);
  return JSON.stringify([f.rotate, f.flip, f.angle]);
};

export const editSelectors = {
  canUndo: (s: EditState) => (s.crop?.active ? s.crop.past.length > 0 : canUndo(s.ed)),
  canRedo: (s: EditState) => (s.crop?.active ? s.crop.future.length > 0 : canRedo(s.ed)),
};

export { AB_DEFAULT_SPLIT };
