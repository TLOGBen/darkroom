/**
 * 編輯 context 的幾何部分：裁切、拉直、旋轉、鏡像（CONTRACT-s3-crop C1–C4、C22–C26）。
 *
 * 唯一的規則在核心函式庫的 Geometry（darkroom/_geometry.py）；這支檔照同一組案例表
 * （tests/cases/s3_geometry_cases.json、s3_geometry_actions.json）鏡像它，所以畫面上的框就是匯出的框。
 * 從舊 logic.js 原樣移植（只加型別），數學不動；單元測試在 domain/__tests__。
 *
 * 資料怎麼流：
 *   - 編輯的 `geometry`（null＝沒有幾何）存在照片庫，預覽／匯出時原樣送後端；
 *   - 裁切模式的「草稿」由 `cropSession` 管（自己的復原堆疊，不進編輯的 reducer），
 *     完成時 `commit` 回傳 `result.changed`，需要時才變成編輯的一步 `setGeometry`。
 */
import { copy, same, zh, type Translate } from './text';

/** 裁切框：0～1，座標是「轉正後的畫面」（旋轉、拉直之後）。 */
export interface Crop {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** 一張照片的幾何。`aspect` 是 'original'、'free' 或 'W:H'。 */
export interface Geometry {
  rotate: number;
  flip: boolean;
  angle: number;
  aspect: string;
  crop: Crop | null;
}

/** 可能缺鍵的幾何（代理或舊資料給的），`fullGeometry` 補齊。 */
export type GeometryLike = Partial<Omit<Geometry, 'crop'>> & { crop?: Crop | null };

export type GeometryAction = 'rotate_right' | 'rotate_left' | 'flip_h' | 'flip_v' | 'orient';
export type CropHandle = 'move' | 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';
type Box = [number, number, number, number];

export const GEOMETRY_IDENTITY: Geometry = { rotate: 0, flip: false, angle: 0, aspect: 'original', crop: null };
export const CROP_EDGES = ['left', 'top', 'right', 'bottom'] as const;
export const RATIO_TOL = 0.001; // verbatim (C3 step 2)
export const CROP_DRAFT_LIMIT = 50; // verbatim：裁切模式自己的復原步數
export const CROP_MIN_PX = 32; // verbatim：畫面上最小的框
export const CROP_KEY_STEP = 0.005; // verbatim：方向鍵 0.5%
export const CROP_KEY_STEP_BIG = 0.05; // verbatim：Shift 5%
export const ANGLE_STEP = 0.1; // verbatim：拉直滑桿
export const CROP_LABEL = zh('crop.label');
export const CROP_HINT = zh('crop.hint');
export const AB_DISABLED_CROP = zh('crop.abDisabled');
export const ORIENT_PORTRAIT = zh('crop.portrait');
export const ORIENT_LANDSCAPE = zh('crop.landscape');

/** C23 常數「比例選單」：值照列的順序（直式）；橫式草稿顯示轉過來的比例（5:4、7:5…）。 */
export const ASPECTS: ReadonlyArray<readonly [string, string]> = [
  ['original', 'crop.aspects.original'],
  ['free', 'crop.aspects.free'],
  ['1:1', 'crop.aspects.r1_1'],
  ['4:5', 'crop.aspects.r4_5'],
  ['5:7', 'crop.aspects.r5_7'],
  ['2:3', 'crop.aspects.r2_3'],
  ['3:4', 'crop.aspects.r3_4'],
  ['16:9', 'crop.aspects.r16_9'],
];

const gcd = (a: number, b: number): number => {
  while (b) [a, b] = [b, a % b];
  return a;
};

/** '8:10' → '4:5'；不是 W:H 的原樣回傳。 */
export function reduceAspect(a: string): string {
  const m = /^(\d+):(\d+)$/.exec(a || '');
  if (!m) return a;
  const w = parseInt(m[1], 10);
  const h = parseInt(m[2], 10);
  const k = gcd(w, h);
  return `${w / k}:${h / k}`;
}

const turnAspect = (a: string): string => (a === 'original' || a === 'free' ? a : a.split(':').reverse().join(':'));

/** 補齊成完整物件（裁切模式的草稿永遠不缺鍵）。 */
export function fullGeometry(g: GeometryLike | null | undefined): Geometry {
  if (!g) return copy(GEOMETRY_IDENTITY);
  return {
    rotate: g.rotate || 0,
    flip: !!g.flip,
    angle: g.angle || 0,
    aspect: g.aspect || 'original',
    crop: g.crop ? { left: g.crop.left, top: g.crop.top, right: g.crop.right, bottom: g.crop.bottom } : null,
  };
}

export const isIdentityGeometry = (g: GeometryLike | null | undefined): boolean =>
  !g || (!g.rotate && !g.flip && !g.angle && !g.crop);

/** C1：等於沒有幾何 → null（只有比例不算）；比例約分。 */
export function normGeometry(g: GeometryLike | null | undefined): Geometry | null {
  if (isIdentityGeometry(g)) return null;
  const f = fullGeometry(g);
  f.aspect = reduceAspect(f.aspect);
  return f;
}

/** 轉正後畫面的寬高（轉 90／270 度時寬高互換）。 */
export const frameSize = (g: Geometry, W: number, H: number): [number, number] =>
  g.rotate === 90 || g.rotate === 270 ? [H, W] : [W, H];

export function ratioOf(g: Geometry, W: number, H: number): number {
  const [fw, fh] = frameSize(g, W, H);
  if (g.aspect === 'original' || g.aspect === 'free') return fw / fh;
  const [a, b] = g.aspect.split(':').map(Number);
  return a / b;
}

const rad = (deg: number) => deg * (Math.PI / 180); // 跟 Python 的 math.radians 同一個算法
const rotv = (phi: number, x: number, y: number): [number, number] => {
  const c = Math.cos(phi);
  const s = Math.sin(phi);
  return [c * x - s * y, s * x + c * y];
};

/** 最大的 s：框 m ± s·e 同時落在畫布與照片裡。 */
function cropLimits(angle: number, m: [number, number], e: [number, number], fw: number, fh: number): number {
  const th = rad(angle);
  const cx = fw / 2;
  const cy = fh / 2;
  const d: [number, number] = [m[0] - cx, m[1] - cy];
  const a = rotv(-th, d[0], d[1]);
  let best = Infinity;
  for (const sx of [1, -1]) {
    for (const sy of [1, -1]) {
      const ek: [number, number] = [sx * e[0], sy * e[1]];
      const bk = rotv(-th, ek[0], ek[1]);
      const rows: Array<[number, number, number]> = [
        [bk[0], cx, a[0]],
        [bk[1], cy, a[1]],
        [ek[0], cx, d[0]],
        [ek[1], cy, d[1]],
      ];
      for (const [val, half, pos] of rows) {
        if (val !== 0) best = Math.min(best, (half - Math.sign(val) * pos) / Math.abs(val));
      }
    }
  }
  return Math.max(0, best);
}

function inPicture(angle: number, m: [number, number], fw: number, fh: number): boolean {
  const a = rotv(-rad(angle), m[0] - fw / 2, m[1] - fh / 2);
  return Math.abs(a[0]) <= fw / 2 && Math.abs(a[1]) <= fh / 2;
}

export interface FitCrop {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
  /** 0～1 的框 [l, t, r, b] */
  box: Box;
}

/** C3：W×H 照片在幾何 g 下的裁切框（像素與 0～1 兩種）。 */
export function fitCrop(geometry: GeometryLike | null | undefined, W: number, H: number): FitCrop {
  const g = fullGeometry(geometry);
  const [fw, fh] = frameSize(g, W, H);
  const rho = ratioOf(g, W, H);
  let m: [number, number];
  let hw: number;
  let hh: number;
  if (!g.crop) {
    // (1) 置中的最大框
    m = [fw / 2, fh / 2];
    const e: [number, number] = [rho / 2, 0.5];
    const s = cropLimits(g.angle, m, e, fw, fh);
    hw = s * e[0];
    hh = s * e[1];
  } else {
    const { left: l, top: t, right: r, bottom: b } = g.crop;
    m = [((l + r) / 2) * fw, ((t + b) / 2) * fh];
    let w = (r - l) * fw;
    let h = (b - t) * fh;
    if (g.aspect !== 'free' && Math.abs(w / h - rho) / rho > RATIO_TOL) {
      // (2) 同中心、同面積
      const area = w * h;
      w = Math.sqrt(area * rho);
      h = Math.sqrt(area / rho);
    }
    if (!inPicture(g.angle, m, fw, fh)) m = [fw / 2, fh / 2]; // (3)
    const s = Math.min(1, cropLimits(g.angle, m, [w / 2, h / 2], fw, fh)); // (4) 只縮不放
    hw = (s * w) / 2;
    hh = (s * h) / 2;
  }
  const x0 = m[0] - hw;
  const y0 = m[1] - hh;
  const x1 = m[0] + hw;
  const y1 = m[1] + hh;
  const box: Box = [x0 / fw, y0 / fh, x1 / fw, y1 / fh];
  // (5) 像素：四捨五入後夾在畫面內，至少 1px
  let L = Math.floor(x0 + 0.5);
  let T = Math.floor(y0 + 0.5);
  let R = Math.floor(x1 + 0.5);
  let B = Math.floor(y1 + 0.5);
  L = Math.min(Math.max(L, 0), fw - 1);
  T = Math.min(Math.max(T, 0), fh - 1);
  R = Math.min(Math.max(R, L + 1), fw);
  B = Math.min(Math.max(B, T + 1), fh);
  return { left: L, top: T, right: R, bottom: B, width: R - L, height: B - T, box };
}

const boxCrop = (b: Box | number[]): Crop => ({ left: b[0], top: b[1], right: b[2], bottom: b[3] });

/** C4 常數「操作表」：旋轉／鏡像／直橫互換只改幾何物件（框跟著照片走）。 */
export function geometryAction(
  geometry: GeometryLike | null | undefined,
  action: GeometryAction,
  W: number,
  H: number,
): Geometry {
  const g = fullGeometry(geometry);
  const c = g.crop;
  let box: Box | null = c ? [c.left, c.top, c.right, c.bottom] : null;
  if (action === 'rotate_right' || action === 'rotate_left') {
    const plus = (action === 'rotate_right') !== g.flip;
    g.rotate = (((g.rotate + (plus ? 90 : -90)) % 360) + 360) % 360;
    if (box) {
      const [l, t, r, b] = box;
      box = action === 'rotate_right' ? [1 - b, l, 1 - t, r] : [t, 1 - r, b, 1 - l];
    }
    g.aspect = turnAspect(g.aspect);
  } else if (action === 'flip_h' || action === 'flip_v') {
    g.flip = !g.flip;
    g.angle = g.angle ? -g.angle : 0;
    if (action === 'flip_v') g.rotate = (g.rotate + 180) % 360;
    if (box) {
      const [l, t, r, b] = box;
      box = action === 'flip_h' ? [1 - r, t, 1 - l, b] : [l, 1 - b, r, 1 - t];
    }
  } else if (action === 'orient') {
    if (g.aspect === 'free' || g.aspect === '1:1') return g;
    const [fw, fh] = frameSize(g, W, H);
    const turned = g.aspect === 'original' ? `${fh / gcd(fw, fh)}:${fw / gcd(fw, fh)}` : turnAspect(g.aspect);
    const start = fitCrop(g, W, H).box;
    g.aspect = turned;
    g.crop = boxCrop(start);
    box = fitCrop(g, W, H).box;
  } else {
    throw new Error('unknown geometry action ' + String(action));
  }
  if (box) g.crop = boxCrop(box);
  return g;
}

/** 草稿目前比例的方向（決定比例選單顯示直式或橫式）。 */
export function cropOrientation(g: GeometryLike | null | undefined, W: number, H: number): 'portrait' | 'landscape' | 'square' {
  const r = ratioOf(fullGeometry(g), W, H);
  return r < 1 ? 'portrait' : r > 1 ? 'landscape' : 'square';
}

/** C23：比例選單 [值, 顯示文字]；橫式時每個比例轉過來，括號裡的相紙尺寸也對調。 */
export function aspectOptions(landscape: boolean, t: Translate = zh): Array<[string, string]> {
  return ASPECTS.map(([v, key]) => {
    const label = t(key);
    if (!landscape || v === 'original' || v === 'free' || v === '1:1') return [v, label] as [string, string];
    const turned = turnAspect(v);
    // 括號樣式照語言檔（中文全形「（8×10）」、英文半形「 (8×10)」），只把兩個數字對調
    const m = /(\s*[（(])(\d+)×(\d+)([）)])/.exec(label);
    return [turned, turned + (m ? `${m[1]}${m[3]}×${m[2]}${m[4]}` : '')] as [string, string];
  });
}

/** 框是否合法：在 0～1 內、有面積，而且 fitCrop 不會再改它。 */
export function cropBoxFits(g: GeometryLike | null | undefined, box: Box | number[], W: number, H: number): boolean {
  const t = fullGeometry(g);
  t.aspect = 'free';
  t.crop = boxCrop(box);
  if (!(box[0] >= 0 && box[1] >= 0 && box[2] <= 1 && box[3] <= 1 && box[0] < box[2] && box[1] < box[3])) return false;
  const r = fitCrop(t, W, H).box;
  return r.every((v, i) => Math.abs(v - box[i]) < 1e-9);
}

function resizedBox(box: Box, handle: CropHandle, dx: number, dy: number, rn: number | null, minW: number, minH: number): Box {
  let [l, t, r, b] = box;
  if (handle === 'move') return [l + dx, t + dy, r + dx, b + dy];
  const W_ = handle.includes('w');
  const E_ = handle.includes('e');
  const N_ = handle.includes('n');
  const S_ = handle.includes('s');
  if (W_) l += dx;
  if (E_) r += dx;
  if (N_) t += dy;
  if (S_) b += dy;
  let w = Math.max(r - l, minW);
  let h = Math.max(b - t, minH);
  if (rn) {
    const horiz = W_ || E_;
    const vert = N_ || S_;
    if (horiz && vert) {
      if (w / rn >= h) h = w / rn;
      else w = h * rn;
    } else if (horiz) h = w / rn;
    else w = h * rn;
    if (w < minW) {
      w = minW;
      h = w / rn;
    }
    if (h < minH) {
      h = minH;
      w = h * rn;
    }
    if (horiz && !vert) {
      const cy = (box[1] + box[3]) / 2;
      t = cy - h / 2;
      b = cy + h / 2;
    }
    if (vert && !horiz) {
      const cx = (box[0] + box[2]) / 2;
      l = cx - w / 2;
      r = cx + w / 2;
    }
  }
  // 對邊留在原地
  if (W_) l = r - w;
  else r = l + w;
  if (N_) t = b - h;
  else b = t + h;
  return [l, t, r, b];
}

export interface CropSize {
  width: number;
  height: number;
  /** 最小框（0～1，由 CROP_MIN_PX 除以畫面上的寬高） */
  minW?: number;
  minH?: number;
}

/** C23：拖把手或整個框 dx、dy（0～1）；鎖定比例會維持；框停在照片邊緣；結果一定通過 fitCrop。 */
export function cropDrag(draft: GeometryLike | null | undefined, size: CropSize, handle: CropHandle, dx: number, dy: number): Geometry {
  const W = size.width;
  const H = size.height;
  const g = fullGeometry(draft);
  const start = fitCrop(g, W, H).box;
  const [fw, fh] = frameSize(g, W, H);
  const rn = g.aspect === 'free' ? null : (ratioOf(g, W, H) * fh) / fw; // 0～1 單位下的比例
  const at = (k: number) => resizedBox(start, handle, dx * k, dy * k, rn, size.minW || 0, size.minH || 0);
  let box = at(1);
  if (!cropBoxFits(g, box, W, H)) {
    // 拖到還放得下的地方為止（二分搜尋）
    let lo = 0;
    let hi = 1;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      if (cropBoxFits(g, at(mid), W, H)) lo = mid;
      else hi = mid;
    }
    box = at(lo);
  }
  g.crop = boxCrop(box);
  g.crop = boxCrop(fitCrop(g, W, H).box); // C3 說了算
  return g;
}

/** 框有焦點時的方向鍵：0.5%（Shift 5%）；不是方向鍵回 null。 */
export function cropKeyMove(key: string, shift: boolean): [number, number] | null {
  const s = shift ? CROP_KEY_STEP_BIG : CROP_KEY_STEP;
  const table: Record<string, [number, number]> = {
    ArrowLeft: [-s, 0],
    ArrowRight: [s, 0],
    ArrowUp: [0, -s],
    ArrowDown: [0, s],
  };
  return table[key] ?? null;
}

/** C22：選了比例但沒畫框 → 完成時框就是該比例的最大框。 */
export function commitGeometry(draft: GeometryLike | null | undefined, W: number, H: number): Geometry | null {
  const g = fullGeometry(draft);
  if (!g.crop && g.aspect !== 'original' && g.aspect !== 'free') g.crop = boxCrop(fitCrop(g, W, H).box);
  return normGeometry(g);
}

/** 裁切模式的狀態：草稿與它自己的復原堆疊（永遠不進編輯的 reducer）。 */
export interface CropSessionState {
  active: boolean;
  entry: Geometry | null;
  draft: Geometry | null;
  past: Geometry[];
  future: Geometry[];
  gesture: string | null;
  result: { changed: boolean; geometry: Geometry | null } | null;
}

export type CropEvent =
  | { type: 'enter'; geometry: GeometryLike | null | undefined }
  | { type: 'change'; draft: GeometryLike | null | undefined; gesture?: string | null }
  | { type: 'endGesture' }
  | { type: 'undo' }
  | { type: 'redo' }
  | { type: 'reset' }
  | { type: 'commit'; width: number; height: number }
  | { type: 'cancel' };

/** C22：裁切模式。commit／cancel 結束它；result.changed 說要不要記一步 setGeometry。 */
export function cropSession(s: CropSessionState | null, ev: CropEvent): CropSessionState | null {
  switch (ev.type) {
    case 'enter':
      return {
        active: true,
        entry: normGeometry(ev.geometry),
        draft: fullGeometry(ev.geometry),
        past: [],
        future: [],
        gesture: null,
        result: null,
      };
    case 'change': {
      if (!s || !s.active) return s;
      const next = fullGeometry(ev.draft);
      const continuing = !!ev.gesture && s.gesture === ev.gesture;
      if (same(next, s.draft)) return continuing ? s : { ...s, gesture: ev.gesture || null };
      const past = continuing ? s.past : s.past.concat([s.draft as Geometry]).slice(-CROP_DRAFT_LIMIT);
      return { ...s, draft: next, past, future: [], gesture: ev.gesture || null };
    }
    case 'endGesture':
      return s && s.gesture ? { ...s, gesture: null } : s;
    case 'undo':
      if (!s || !s.active || !s.past.length) return s;
      return {
        ...s,
        draft: s.past[s.past.length - 1],
        past: s.past.slice(0, -1),
        future: s.future.concat([s.draft as Geometry]),
        gesture: null,
      };
    case 'redo':
      if (!s || !s.active || !s.future.length) return s;
      return {
        ...s,
        draft: s.future[s.future.length - 1],
        future: s.future.slice(0, -1),
        past: s.past.concat([s.draft as Geometry]),
        gesture: null,
      };
    case 'reset':
      return cropSession(s, { type: 'change', draft: null });
    case 'commit': {
      if (!s || !s.active) return s;
      const g = commitGeometry(s.draft, ev.width, ev.height);
      return {
        active: false,
        entry: s.entry,
        draft: null,
        past: [],
        future: [],
        gesture: null,
        result: { changed: !same(g, s.entry), geometry: g },
      };
    }
    case 'cancel':
      if (!s || !s.active) return s;
      return {
        active: false,
        entry: s.entry,
        draft: null,
        past: [],
        future: [],
        gesture: null,
        result: { changed: false, geometry: s.entry },
      };
    default:
      throw new Error('unknown crop event ' + (ev as { type: string }).type);
  }
}

/** C24：換照片時裁切永遠不沿用。 */
export const carryGeometry = (): null => null;

/** C25：原圖預覽依「照片＋幾何（＋裁切模式的整個畫面）」快取。 */
export const originalKey = (imageId: string, geometry: GeometryLike | null | undefined, frame: boolean): string =>
  `${imageId}|${JSON.stringify(normGeometry(geometry))}|${frame ? 1 : 0}`;
