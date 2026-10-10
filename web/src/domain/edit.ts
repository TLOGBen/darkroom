/**
 * 編輯 context（調色部分）：滑桿語意、編輯狀態的 reducer、復原／重做、曲線、自動存檔的請求內容。
 *
 * 從舊 logic.js 原樣移植（契約 R3 滑桿語意、R5 復原歷史、R6 輸入數值與曲線、S2／S3 Preset 快照、S7 對照、S17 滑桿繪製），
 * 只加型別；行為以 domain/__tests__ 裡從 tests/js/test_logic.cjs 搬來的案例為準。
 *
 * 資料怎麼流：
 *   使用者動作 → hooks/useEditorStore 的 dispatch → 本檔 `reduce`（純函式，產生新狀態並記一步歷史）
 *   → 新狀態觸發預覽（usePreview，只送最新一次）與自動存檔（hooks/autosave：`editRequest` 決定送 PUT 還是 paste）。
 * 滑桿的畫面值＝clamp(preset×強度) ＋ 微調；微調（tweak）永遠從畫面上看到的值量起（`tweakFor`）。
 */
import { carryGeometry, normGeometry, type Geometry, type GeometryLike } from './geometry';
import { copy, round, same, zh, type Translate } from './text';

// ---------------------------------------------------------------------------------------------------------------------
// 型別（名稱照 CONTEXT.md 詞條：Slider、Overrides、Edit、PresetSnapshot…）
// ---------------------------------------------------------------------------------------------------------------------

/** 一個滑桿（後端 GET /api/sliders 的一列）：Lightroom crs 鍵名、範圍、預設、步進。 */
export interface Slider {
  key: string;
  label: string;
  group: string;
  min: number;
  max: number;
  default: number;
  step: number;
  /** HSL 的子分頁：h 色相、s 飽和度、l 明度 */
  sub?: 'h' | 's' | 'l' | null;
  /** 色相角度不隨強度縮放 */
  hue?: boolean;
}

/** 滑桿表：GET /api/sliders。groups 是 [代號, 中文名] 的有序清單。 */
export interface SliderTable {
  sliders: Slider[];
  groups: Array<[string, string]>;
}

/** 微調：滑桿鍵 → 差值（加在 preset×強度之後）。 */
export type Overrides = Record<string, number>;

/** 曲線點 [x, y]，0～255。 */
export type CurvePoint = [number, number];

/** Preset 的參數（darkroom-params/1）；快照與詳細資料都用這個形狀。 */
export interface PresetParams {
  schema?: string;
  values?: Record<string, number>;
  curves?: Record<string, CurvePoint[]>;
  masks?: unknown[];
  skipped?: unknown[];
}

/** Preset 快照：編輯在套用當下抄一份 preset 參數，之後 preset 改了不影響已套上的編輯（PL8）。 */
export interface PresetSnapshot {
  id: string;
  name: string;
  group: string;
  params: PresetParams;
}

/** 照片庫裡存的一份編輯（GET /api/edit 的 edit）。 */
export interface Edit {
  schema?: string;
  fingerprint?: string;
  preset: PresetSnapshot | null;
  strength: number;
  overrides: Overrides;
  geometry?: Geometry | null;
}

/** 滑桿畫面上看到的一組值。 */
export interface SliderView {
  /** preset × 強度（未夾） */
  raw: number;
  /** 夾在範圍內的 preset × 強度 */
  base: number;
  /** 畫面值＝clamp(base + tweak) */
  value: number;
  clamped: 'min' | 'max' | null;
  tweak: number;
}

/** 編輯器用的 preset 細節：滑桿基準值、曲線、套不上的設定說明。 */
export interface PresetDetailView {
  id: string;
  name: string;
  group: string;
  values: Record<string, number>;
  curves: Record<string, CurvePoint[]>;
  banner: string;
  note: string;
  snapshot?: boolean;
}

// ---------------------------------------------------------------------------------------------------------------------
// R3 滑桿語意
// ---------------------------------------------------------------------------------------------------------------------

type Range = { min: number; max: number };
const clampTo = (s: Range, v: number) => Math.min(s.max, Math.max(s.min, v));

/** raw＝preset 值依強度縮放（色相不縮）；base＝clamp(raw)；畫面值＝clamp(base + tweak)。 */
export function sliderView(s: Slider, presetValue: number, strengthPct: number, tweak?: number): SliderView {
  const raw = s.hue ? presetValue : s.default + (strengthPct / 100) * (presetValue - s.default);
  const base = clampTo(s, raw);
  const clamped = raw < s.min ? 'min' : raw > s.max ? 'max' : null;
  return { raw, base, value: clampTo(s, base + (tweak || 0)), clamped, tweak: tweak || 0 };
}

/** 使用者把滑桿拉到 value 時的微調：從畫面上看到的 base 量起；不到半步算 0。 */
export function tweakFor(s: Slider, presetValue: number, strengthPct: number, value: number): number {
  const d = clampTo(s, value) - sliderView(s, presetValue, strengthPct, 0).base;
  return Math.abs(d) < s.step / 2 ? 0 : round(d, 6);
}

/** 滑桿數值的顯示：步進 <1 兩位小數；雙向滑桿正數帶 +。 */
export function fmtNum(s: Slider, v: number): string {
  if (s.step < 1) return (v > 0 && s.min < 0 ? '+' : '') + v.toFixed(2);
  const r = Math.round(v);
  return (r > 0 && s.min < 0 ? '+' : '') + r;
}

export const fmtRaw = (v: number): string => String(round(v, 2));

/** 被夾住時數值旁的註記：「（原 -112.5）」。 */
export const clampNote = (view: SliderView, t: Translate = zh): string =>
  view.clamped ? t('editor.clampNote', { raw: fmtRaw(view.raw) }) : '';

/** 滑桿列的提示：preset × 強度 = 原值，夾住到哪、微調多少；最後提醒雙擊還原。 */
export function sliderTooltip(s: Slider, presetValue: number, strengthPct: number, tweak: number, t: Translate = zh): string {
  const v = sliderView(s, presetValue, strengthPct, tweak);
  let out = t('editor.tip.base', { strength: strengthPct, raw: fmtRaw(v.raw) });
  if (v.clamped)
    out += t(v.clamped === 'min' ? 'editor.tip.atMin' : 'editor.tip.atMax', {
      limit: fmtRaw(v.clamped === 'min' ? s.min : s.max),
    });
  if (v.tweak) out += t('editor.tip.tweak', { tweak: (v.tweak > 0 ? '+' : '') + fmtRaw(v.tweak) });
  return out + t('editor.tip.reset');
}

/** 滑桿的 aria-valuetext：帶單位與狀態（DESIGN.md §8）。 */
export function sliderValueText(s: Slider, view: SliderView, label: string, t: Translate = zh): string {
  let out = `${label} ${fmtNum(s, view.value)}`;
  if (view.tweak) out += t('editor.aria.adjusted');
  if (view.clamped) out += t('editor.aria.clamped');
  return out;
}

// ---------------------------------------------------------------------------------------------------------------------
// R5 復原歷史（舊版的 History 類別；編輯器本身用下面的 reducer，這個類別保留給測試與其他小工具）
// ---------------------------------------------------------------------------------------------------------------------

export class History<T> {
  limit: number;
  past: T[] = [];
  future: T[] = [];
  constructor(limit?: number) {
    this.limit = limit || 200;
  }
  /** 記下改變之前的狀態 */
  push(state: T): void {
    const s = copy(state);
    if (!this.past.length || !same(this.past[this.past.length - 1], s)) {
      this.past.push(s);
      if (this.past.length > this.limit) this.past.shift();
    }
    this.future = [];
  }
  undo(current: T): T | null {
    if (!this.past.length) return null;
    this.future.push(copy(current));
    return this.past.pop() as T;
  }
  redo(current: T): T | null {
    if (!this.future.length) return null;
    this.past.push(copy(current));
    return this.future.pop() as T;
  }
  canUndo(): boolean {
    return this.past.length > 0;
  }
  canRedo(): boolean {
    return this.future.length > 0;
  }
}

// ---------------------------------------------------------------------------------------------------------------------
// R5 編輯狀態（reducer）
// ---------------------------------------------------------------------------------------------------------------------

/** 一步歷史記的東西：preset、強度、微調、幾何（S3 C24：裁切／旋轉也是狀態的一部分）。 */
export interface EditorSnapshot {
  presetId: string | null;
  strength: number;
  tweaks: Overrides;
  geometry: Geometry | null;
}

export interface EditorState extends EditorSnapshot {
  past: EditorSnapshot[];
  future: EditorSnapshot[];
  /** 進行中的手勢（一次拖曳＝一步）；null＝沒有 */
  gesture: string | null;
}

export type EditorAction =
  | { type: 'selectPreset'; id?: string | null }
  | { type: 'setStrength'; value: number; gesture?: string | null }
  | { type: 'setValue'; slider: Slider; presetValue: number; value: number; gesture?: string | null }
  | { type: 'resetKey'; key: string }
  | { type: 'resetAll' }
  | { type: 'resetToOriginal' }
  | { type: 'setGeometry'; geometry: GeometryLike | null }
  | { type: 'carry' }
  | { type: 'endGesture' }
  | { type: 'restoreEdit'; edit: Pick<Edit, 'preset' | 'strength' | 'overrides'> & { geometry?: GeometryLike | null } }
  | { type: 'undo' }
  | { type: 'redo' };

export const HISTORY_LIMIT = 200;

const snap = (ed: EditorSnapshot): EditorSnapshot => ({
  presetId: ed.presetId,
  strength: ed.strength,
  tweaks: { ...ed.tweaks },
  geometry: ed.geometry ? copy(ed.geometry) : null,
});

export function initialEditor(): EditorState {
  return { presetId: null, strength: 100, tweaks: {}, geometry: null, past: [], future: [], gesture: null };
}

/** 沒有 preset 時強度停用（也不生效）。 */
export const strengthEnabled = (ed: EditorSnapshot): boolean => ed.presetId !== null;
/** 實際生效的強度：沒有 preset 時微調以 100% 套用。 */
export const strengthInEffect = (ed: EditorSnapshot): number => (ed.presetId === null ? 100 : ed.strength);
export const canUndo = (ed: EditorState): boolean => ed.past.length > 0;
export const canRedo = (ed: EditorState): boolean => ed.future.length > 0;

export const CARRY_HINT = zh('topbar.carryHint');
export const CARRY_HINT_SHORT = zh('topbar.carryHintShort');

/** S11：只有「沿用上一張」（這張還沒有編輯）時才提示；已存的編輯不用提示。 */
export const carryHintVisible = (ed: EditorSnapshot, hasImage: boolean, hasEdit: boolean): boolean =>
  !!hasImage && !hasEdit && (ed.presetId !== null || Object.keys(ed.tweaks).length > 0);

/** 每個改變記下「之前」的狀態；同一個手勢的後續步驟不再記；什麼都沒變就不記。 */
function change(ed: EditorState, next: Partial<EditorSnapshot>, gesture?: string | null): EditorState {
  const now = snap(ed);
  if (same(now, snap({ ...ed, ...next }))) {
    // 沒變：手勢要真的改過東西才算開始
    const keep = gesture && ed.gesture === gesture ? gesture : null;
    return keep === ed.gesture ? ed : { ...ed, gesture: keep };
  }
  const continuing = !!gesture && ed.gesture === gesture;
  const past = continuing ? ed.past : ed.past.concat([now]).slice(-HISTORY_LIMIT);
  return { ...ed, ...next, past, future: [], gesture: gesture || null };
}

export function reduce(ed: EditorState, a: EditorAction): EditorState {
  switch (a.type) {
    case 'selectPreset': // 強度與微調都保留
      return change(ed, { presetId: a.id === undefined ? null : a.id });
    case 'setStrength': {
      if (!strengthEnabled(ed)) return ed;
      const v = Math.min(200, Math.max(0, Math.round(a.value)));
      return change(ed, { strength: v }, a.gesture);
    }
    case 'setValue': {
      const d = tweakFor(a.slider, a.presetValue, strengthInEffect(ed), a.value);
      const tweaks = { ...ed.tweaks };
      if (d) tweaks[a.slider.key] = d;
      else delete tweaks[a.slider.key];
      return change(ed, { tweaks }, a.gesture);
    }
    case 'resetKey': {
      if (!(a.key in ed.tweaks)) return ed;
      const tweaks = { ...ed.tweaks };
      delete tweaks[a.key];
      return change(ed, { tweaks });
    }
    case 'resetAll':
      return Object.keys(ed.tweaks).length ? change(ed, { tweaks: {} }) : ed;
    case 'resetToOriginal': // S10：沒有 preset、沒有微調、沒有幾何；一步（強度保留）
      return change(ed, { presetId: null, tweaks: {}, geometry: null });
    case 'setGeometry': // S3 C22／C24：裁切模式的結果，或模式外的旋轉／鏡像：一步
      return change(ed, { geometry: normGeometry(a.geometry) });
    case 'carry': {
      // C24：開了另一張照片——裁切是那張自己的，永遠不沿用（歷史裡的也一起換掉）
      const g = carryGeometry();
      const drop = (list: EditorSnapshot[]) => list.map((x) => ({ ...x, geometry: g }));
      return { ...ed, geometry: g, past: drop(ed.past), future: drop(ed.future), gesture: null };
    }
    case 'endGesture':
      return ed.gesture ? { ...ed, gesture: null } : ed;
    case 'restoreEdit': {
      // PL15／PLP9：照片存好的編輯回來了；歷史重新開始
      const e = a.edit;
      return {
        presetId: e.preset ? e.preset.id : null,
        strength: e.strength,
        tweaks: { ...e.overrides },
        geometry: normGeometry(e.geometry === undefined ? null : e.geometry),
        past: [],
        future: [],
        gesture: null,
      };
    }
    case 'undo': {
      if (!canUndo(ed)) return ed;
      const prev = ed.past[ed.past.length - 1];
      return { ...ed, ...copy(prev), past: ed.past.slice(0, -1), future: ed.future.concat([snap(ed)]), gesture: null };
    }
    case 'redo': {
      if (!canRedo(ed)) return ed;
      const next = ed.future[ed.future.length - 1];
      return { ...ed, ...copy(next), past: ed.past.concat([snap(ed)]), future: ed.future.slice(0, -1), gesture: null };
    }
    default:
      throw new Error('unknown action ' + (a as { type: string }).type);
  }
}

/** 兩個編輯狀態「畫面上」是否相同（不比歷史）。 */
export const sameEditorState = (a: EditorSnapshot, b: EditorSnapshot): boolean =>
  a.presetId === b.presetId &&
  a.strength === b.strength &&
  JSON.stringify(a.tweaks) === JSON.stringify(b.tweaks) &&
  JSON.stringify(a.geometry) === JSON.stringify(b.geometry);

/** 只留非零的微調（送後端用）。 */
export const nonZeroOverrides = (tweaks: Overrides): Overrides =>
  Object.fromEntries(Object.entries(tweaks).filter(([, d]) => d));

// ---------------------------------------------------------------------------------------------------------------------
// R6 直接輸入數值、曲線
// ---------------------------------------------------------------------------------------------------------------------

/** 直接輸入的數字：接受 +、Unicode 減號、結尾 %；超出範圍夾住；不是數字回 null。 */
export function parseValueInput(text: string | null | undefined, s: Range): number | null {
  const v = String(text || '')
    .trim()
    .replace(/[−–]/g, '-')
    .replace(/[%％]$/, '')
    .replace(/^\+/, '');
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(v)) return null;
  return clampTo(s, parseFloat(v));
}

/** 曲線依強度：每個點從對角線往 preset 的位置移 k 倍。 */
export function curveAtStrength(points: CurvePoint[], strengthPct: number): CurvePoint[] {
  const k = strengthPct / 100;
  return points.map(([x, y]) => [x, Math.min(255, Math.max(0, round(x + k * (y - x), 6)))] as CurvePoint);
}

/** 曲線的 SVG path（size×size，y 軸朝上）；兩端補到 0 與 255。 */
export function curvePath(points: CurvePoint[], size: number): string {
  const pts = [...points].sort((a, b) => a[0] - b[0]);
  if (!pts.length) return '';
  const f = (v: number) => ((v / 255) * size).toFixed(1);
  const g = (v: number) => ((1 - v / 255) * size).toFixed(1);
  const all: CurvePoint[] = pts[0][0] > 0 ? [[0, pts[0][1]], ...pts] : pts;
  const last = all[all.length - 1];
  if (last[0] < 255) all.push([255, last[1]]);
  return all.map(([x, y], i) => (i ? 'L' : 'M') + f(x) + ' ' + g(y)).join(' ');
}

/** 點曲線的四個通道與畫線顏色（RGB 曲線的紅綠藍是資料本身，DESIGN.md §2.3）。 */
export const CURVE_CHANNELS: ReadonlyArray<readonly [string, string]> = [
  ['ToneCurvePV2012', '#e0e0e0'],
  ['ToneCurvePV2012Red', '#ff6060'],
  ['ToneCurvePV2012Green', '#60d060'],
  ['ToneCurvePV2012Blue', '#6090ff'],
];

// ---------------------------------------------------------------------------------------------------------------------
// S17 滑桿繪製：CSS 變數、色相點、照片底色
// ---------------------------------------------------------------------------------------------------------------------

const pct = (s: Range, v: number) => Math.max(0, Math.min(100, ((clampTo(s, v) - s.min) / (s.max - s.min)) * 100));

export interface SliderVars {
  base: string;
  lo: string;
  hi: string;
}

/** --dr-base＝preset 落點；--dr-lo～--dr-hi＝從落點到把手（你的微調）；都是 0～100% 的範圍位置。 */
export function sliderVars(s: Range, view: Pick<SliderView, 'base' | 'value'>): SliderVars {
  const a = pct(s, view.base);
  const b = pct(s, view.value);
  return { base: a.toFixed(2) + '%', lo: Math.min(a, b).toFixed(2) + '%', hi: Math.max(a, b).toFixed(2) + '%' };
}

/** 強度轉盤：0～200，100 在正中間。 */
export function strengthVars(strength: number): SliderVars {
  const a = 50;
  const b = Math.max(0, Math.min(100, strength / 2));
  return { base: '50%', lo: Math.min(a, b).toFixed(2) + '%', hi: Math.max(a, b).toFixed(2) + '%' };
}

export const bipolar = (s: Range): boolean => s.min < 0 && s.max > 0;

export const HUE_DOTS: Readonly<Record<string, string>> = {
  Red: '#e04848',
  Orange: '#e08a3c',
  Yellow: '#d9c43a',
  Green: '#4fb24f',
  Aqua: '#3fb8a8',
  Blue: '#4a7fe0',
  Purple: '#8c5fd6',
  Magenta: '#d65aa8',
};

/** HSL 列：標籤前 6px 色點的顏色（永遠不上軌道）；不是 HSL 列回 null。 */
export function hueDot(key: string): string | null {
  const m = /^(?:Hue|Saturation|Luminance)Adjustment(\w+)$/.exec(key);
  return m && HUE_DOTS[m[1]] ? HUE_DOTS[m[1]] : null;
}

export const CANVASES = ['dark', 'black', 'mid'] as const;
export type Canvas = (typeof CANVASES)[number];
export const CANVAS_STORAGE_KEY = 'darkroom.canvas';
export const canvasFrom = (stored: unknown): Canvas =>
  (CANVASES as readonly unknown[]).includes(stored) ? (stored as Canvas) : 'dark';

// ---------------------------------------------------------------------------------------------------------------------
// S7 A/B 對照：分隔線位置（永遠不進 reducer）
// ---------------------------------------------------------------------------------------------------------------------

export const AB_KEY = 'y';
export const AB_STORAGE_KEY = 'darkroom.abSplit';
export const AB_DEFAULT_SPLIT = 0.5;
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** 分隔線把手的鍵盤：←→ 1%（Shift 10%）、Home／End；不是我們的鍵回 null。 */
export function abStep(split: number, key: string, shift: boolean): number | null {
  const step = shift ? 0.1 : 0.01;
  switch (key) {
    case 'ArrowLeft':
      return clamp01(split - step);
    case 'ArrowRight':
      return clamp01(split + step);
    case 'Home':
      return 0;
    case 'End':
      return 1;
    default:
      return null;
  }
}

/** sessionStorage 的值 → 0～1，讀不懂就用預設。 */
export function abSplitFrom(stored: string | null | undefined): number {
  const v = parseFloat(String(stored));
  return Number.isFinite(v) && v >= 0 && v <= 1 ? v : AB_DEFAULT_SPLIT;
}

// ---------------------------------------------------------------------------------------------------------------------
// PL15／S2／S3：自動存檔的請求、Preset 快照當滑桿基準
// ---------------------------------------------------------------------------------------------------------------------

/** PUT /api/edit 的內容：目前這張照片的編輯（畫面上看到的樣子）。 */
export interface EditBody {
  path: string;
  preset_id: string | null;
  strength: number;
  overrides: Overrides;
  geometry: Geometry | null;
}

export function editBody(ed: EditorSnapshot, path: string): EditBody {
  // C24：幾何一定一起送（null 也送：代表「沒有」，不是「保留存好的」）
  return { path, preset_id: ed.presetId, strength: strengthInEffect(ed), overrides: nonZeroOverrides(ed.tweaks), geometry: normGeometry(ed.geometry) };
}

export type EditRequest =
  | { method: 'PUT'; body: EditBody }
  | {
      method: 'PASTE';
      body: { targets: string[]; edit: Edit & { schema: string; fingerprint: string }; with_geometry: true };
    };

/**
 * S2：照片 `path` 在狀態 `ed` 時的自動存檔請求。頁面記得這個 preset 的快照時（從這張的 GET／PUT /api/edit 來），
 * 用 paste 把那份快照原樣寫回（PL8：永遠不重讀 preset 庫），否則用 PUT（PL4）。
 */
export function editRequest(
  ed: EditorSnapshot,
  path: string,
  snapshots: Record<string, PresetSnapshot> | null | undefined,
  fingerprint: string | null | undefined,
): EditRequest {
  const body = editBody(ed, path);
  const s = ed.presetId !== null && snapshots ? snapshots[ed.presetId] : null;
  if (!s) return { method: 'PUT', body };
  const edit: Edit & { schema: string; fingerprint: string } = {
    schema: body.geometry ? 'darkroom-edit/2' : 'darkroom-edit/1',
    fingerprint: fingerprint || '',
    preset: s,
    strength: body.strength,
    overrides: body.overrides,
  };
  if (body.geometry) edit.geometry = body.geometry; // C12：/2 只在有幾何時
  // S2b：頁面自己存檔要連幾何一起（paste 預設保留目標的幾何，那會丟掉剛裁好的框）
  return { method: 'PASTE', body: { targets: [path], edit, with_geometry: true } };
}

/** preset 庫的細節（GET /api/presets/{id}）裡編輯器會用到的部分。 */
export interface PresetDetailLike {
  id?: string;
  name?: string;
  group?: string;
  values?: Record<string, number>;
  curves?: Record<string, CurvePoint[]>;
  banner?: string;
  note?: string;
}

/** S3：滑桿基準與曲線來自編輯的快照（不是 preset 庫現在的檔）；套不上的說明仍來自庫裡的細節（還在的話）。 */
export function detailFromSnapshot(snapshot: PresetSnapshot, detail: PresetDetailLike | null | undefined): PresetDetailView {
  const p = snapshot.params || {};
  return {
    id: snapshot.id,
    name: snapshot.name,
    group: snapshot.group,
    values: { ...(p.values || {}) },
    curves: { ...(p.curves || {}) },
    banner: detail ? detail.banner || '' : '',
    note: detail ? detail.note || '' : '',
    snapshot: true,
  };
}

/** 「存成 preset」需要 preset 或至少一個微調。 */
export const canSavePreset = (ed: EditorSnapshot): boolean =>
  ed.presetId !== null || Object.keys(ed.tweaks).some((k) => ed.tweaks[k]);
