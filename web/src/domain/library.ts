/**
 * 照片庫 context：照片、資料夾、縮圖格（篩選、多選、角標）、自動存檔的節奏與重試、批次動作的句子。
 *
 * 從舊 logic.js 移植（PL15／PLP9 照片庫、S8～S13 縮圖格與存檔、C29 讀不到的編輯不覆蓋），只加型別。
 * 資料怎麼流：
 *   - 編輯以照片「內容」的 SHA-256（PhotoFingerprint）對應，存在 data_dir；前端只送照片路徑，路徑只讀不寫。
 *   - 開著的照片改了什麼，AUTOSAVE_MS 後送出最新的一份（hooks/autosave）；失敗退避 SAVE_RETRY_MS 重試一次。
 *   - 縮圖格：GET /api/folder/thumbnails 列出照片，每格看得到時才 GET /api/thumbnail（X-Edited／X-Edit 標頭帶角標資料）。
 */
import type { Edit } from './edit';
import { zh, type Translate } from './text';

/** POST /api/open 的回應＋開啟時的路徑。 */
export interface Photo {
  image_id: string;
  width: number;
  height: number;
  preview_width: number;
  preview_height: number;
  path: string;
}

/** 照片內容的 SHA-256：編輯就是用它對應到照片。 */
export type PhotoFingerprint = string;

/** GET /api/folder：同資料夾支援的照片（依檔名排序）與目前這張的位置（-1＝不在清單裡）。 */
export interface PhotoFolder {
  folder?: string;
  files: Array<{ name: string; path: string }>;
  index: number;
}

/** 縮圖格的一格（GET /api/folder/thumbnails 的 items）；edited 為 null＝還沒判定。 */
export interface Thumbnail {
  name: string;
  path: string;
  fingerprint?: string | null;
  edited?: boolean | null;
}

/** GET /api/edit 的回應：編輯、preset 狀態、有沒有一份可以取回的上一份編輯。 */
export interface EditInfo {
  fingerprint?: string | null;
  edit: Edit | null;
  preset_status?: 'current' | 'changed' | 'missing' | null;
  /** PreviousEdit：被清掉、可以取回的那一份還在不在 */
  previous?: boolean;
}
export type PreviousEdit = boolean;

/** 縮圖角標資料（X-Edit 標頭，S8）。 */
export interface BadgeInfo {
  preset?: string | null;
  strength?: number;
  status?: string | null;
  geometry?: boolean;
  tweaks?: boolean;
}

export const AUTOSAVE_MS = 500;
export const SAVE_RETRY_MS = 2000; // S13 (g)：失敗後重試一次的退避時間

/**
 * S13g'：一個失敗存檔的重試時機，看「現在排隊的是哪張」：同一張有更新的改變＝被取代；
 * 別張在排隊＝等它先送；沒有排隊＝現在送。
 */
export const retryDue = (pendingPath: string | null | undefined, retryPath: string): 'now' | 'superseded' | 'after' =>
  pendingPath == null ? 'now' : pendingPath === retryPath ? 'superseded' : 'after';

/** 頁面關掉時要送的：每個還在退避的失敗存檔（除非同一張有更新的排隊），再加上排隊中的那份。 */
export const unloadJobs = <J extends { path: string }>(pending: J | null | undefined, retries: J[]): J[] => [
  ...retries.filter((r) => !pending || r.path !== pending.path),
  ...(pending ? [pending] : []),
];

export const openFailed = (fileName: string, reason: string, t: Translate = zh) =>
  t('photo.openFailed', { file: fileName, reason });
export const GRID_EMPTY = zh('grid.empty');

// ---------------------------------------------------------------------------------------------------------------------
// S8／S9／S10 縮圖格：角標、篩選、還原／取回
// ---------------------------------------------------------------------------------------------------------------------

export const FILTERS = ['all', 'edited', 'plain'] as const;
export type GridFilter = (typeof FILTERS)[number];
export const FILTER_LABELS: Record<GridFilter, string> = {
  all: zh('grid.filter.all'),
  edited: zh('grid.filter.edited'),
  plain: zh('grid.filter.plain'),
};
export const BADGE_ONLY_TWEAKS = zh('grid.badge.onlyTweaks');
export const BADGE_CHANGED = zh('grid.badge.changed');
export const BADGE_MISSING = zh('grid.badge.missing');
export const BADGE_ONLY_GEOMETRY = zh('grid.badge.onlyGeometry');
export const BADGE_CROPPED = zh('grid.badge.cropped');

/** 角標的提示文字：哪個 preset、多強、有沒有過期；只有微調或只有裁切另外說。 */
export function badgeTitle(info: BadgeInfo | null | undefined, t: Translate = zh): string {
  if (!info) return t('grid.badge.edited');
  // S8b（C18）：只有有 preset 時才寫強度；有顏色又有幾何時加「・已裁切」
  let out = info.preset
    ? t('grid.badge.preset', { preset: info.preset, strength: info.strength })
    : info.geometry && !info.tweaks
      ? t('grid.badge.onlyGeometry')
      : t('grid.badge.onlyTweaks');
  if (info.geometry && (info.preset || info.tweaks)) out += t('grid.badge.cropped');
  return (
    out + (info.status === 'changed' ? t('grid.badge.changed') : info.status === 'missing' ? t('grid.badge.missing') : '')
  );
}

/** 編輯的 preset 已改或不見（角標畫空心圈）。 */
export const stale = (info: BadgeInfo | null | undefined): boolean =>
  !!info && (info.status === 'changed' || info.status === 'missing');

/** 篩選：{shown: [[原索引, 項目]], pending: 還沒判定的張數（只有篩選時才算）}。 */
export function gridFilter<T extends { edited?: boolean | null }>(
  items: T[],
  filter: GridFilter | string,
): { shown: Array<[number, T]>; pending: number } {
  const shown: Array<[number, T]> = [];
  const unknown = items.filter((it) => it.edited === null || it.edited === undefined).length;
  items.forEach((it, i) => {
    if (filter === 'edited' ? it.edited === true : filter === 'plain' ? it.edited === false : true) shown.push([i, it]);
  });
  return { shown, pending: filter === 'all' ? 0 : unknown };
}

/** S9：篩選中只能選看得到的格——Shift 範圍不會選到藏起來的照片。永遠回新的 Set。 */
export const onlyShown = (sel: Set<number>, shown: Set<number> | null | undefined): Set<number> =>
  shown ? new Set([...sel].filter((i) => shown.has(i))) : new Set(sel);

export const gridPending = (k: number, t: Translate = zh) => t('grid.pending', { n: k });
export const resetConfirm = (n: number, t: Translate = zh) => t('grid.resetConfirm', { n });
export const resetDone = (ok: number, failed: number, t: Translate = zh) => t('grid.resetDone', { ok, failed });
export const restoreDone = (ok: number, failed: number, t: Translate = zh) => t('grid.restoreDone', { ok, failed });
export const RESET_TOAST = zh('editor.resetToast');
export const RESTORE_TOAST = zh('editor.restoreToast');
export const PRESET_CHANGED = zh('editor.presetChanged');
export const PRESET_MISSING = zh('editor.presetMissing');
export const presetStatusText = (status: string | null | undefined, t: Translate = zh): string =>
  status === 'changed' ? t('editor.presetChanged') : status === 'missing' ? t('editor.presetMissing') : '';
export const copied = (sourceName: string, t: Translate = zh) => t('grid.copied', { name: sourceName });
export const pasteConfirm = (sourceName: string, n: number, t: Translate = zh) => t('grid.pasteConfirm', { name: sourceName, n });
export const PASTE_GEOMETRY_LABEL = zh('grid.pasteGeometry');
export const PASTE_GEOMETRY_NOTE = zh('grid.pasteGeometryNote');
export const pasteConfirmWith = (sourceName: string, n: number, withGeometry: boolean, t: Translate = zh) =>
  pasteConfirm(sourceName, n, t) + (withGeometry ? t('grid.pasteGeometryNote') : '');
export const pasteDone = (ok: number, failed: number, t: Translate = zh) => t('grid.pasteDone', { ok, failed });
export const exportSelectedDone = (ok: number, failed: number, t: Translate = zh) => t('grid.exportDone', { ok, failed });
export const gridCount = (n: number, total: number, t: Translate = zh) => t('grid.count', { n, total });
export const saveEditFailed = (reason: string, t: Translate = zh) => t('photo.saveEditFailed', { reason });
export const loadEditFailed = (reason: string, t: Translate = zh) => t('photo.loadEditFailed', { reason });
export const loadFolderFailed = (reason: string, t: Translate = zh) => t('grid.loadFolderFailed', { reason });

/**
 * S3 封緘（C29）：讀不到已存編輯的照片永遠不會被自動存檔蓋掉——畫面上的狀態不是那份編輯，
 * 自動存檔會把存好的裁切與顏色換成它。
 */
export const EDIT_UNREADABLE = zh('editor.editUnreadable');
export const saveAllowed = (unreadablePath: string | null | undefined, path: string): boolean =>
  unreadablePath == null || unreadablePath !== path;

/** 點一下＝只選這格；Ctrl＝切換這格；Shift＝錨點到這格。 */
export function gridSelect(
  sel: Set<number>,
  i: number,
  mods: { ctrl?: boolean; shift?: boolean } | null | undefined,
  anchor: number | null | undefined,
): { sel: Set<number>; anchor: number } {
  const out = new Set<number>(mods && mods.ctrl ? sel : []);
  if (mods && mods.shift) {
    const a = anchor == null ? 0 : anchor;
    for (let k = Math.min(a, i); k <= Math.max(a, i); k++) out.add(k);
    return { sel: out, anchor: a };
  }
  if (mods && mods.ctrl) {
    if (out.has(i)) out.delete(i);
    else out.add(i);
    return { sel: out, anchor: i };
  }
  out.add(i);
  return { sel: out, anchor: i };
}

/** edits：{路徑: GET /api/edit 的結果 | null（讀取失敗）} → 匯出項目與失敗數。 */
export function exportItems(
  paths: string[],
  edits: Record<string, EditInfo | null | undefined>,
): { items: Array<Record<string, unknown>>; failed: number } {
  const items: Array<Record<string, unknown>> = [];
  let failed = 0;
  for (const p of paths) {
    const r = edits[p];
    if (!r) {
      failed++;
      continue;
    }
    if (r.edit)
      items.push({
        path: p,
        preset_id: r.edit.preset ? r.edit.preset.id : null,
        strength: r.edit.strength,
        overrides: r.edit.overrides,
      });
    else items.push({ path: p });
  }
  return { items, failed };
}

/** 照片所在資料夾（去掉最後一段）。 */
export const folderOf = (path: string): string => path.replace(/[\\/][^\\/]*$/, '');

/** 使用者貼上的路徑常帶引號（檔案總管「複製路徑」）；去掉頭尾空白與引號。 */
export const cleanPath = (p: string | null | undefined): string => (p || '').trim().replace(/^"|"$/g, '');
