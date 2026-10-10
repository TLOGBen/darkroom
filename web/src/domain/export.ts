/**
 * 匯出 context：匯出設定（8 個鍵）、匯出預設、匯出對話框哪些控制項停用、一行摘要、輸出尺寸的鏡像計算。
 *
 * 從舊 logic.js 移植（X13 匯出、S2 E1／E8／E29 匯出對話框），只加型別。
 * 唯一的規則是伺服器的 normalize_settings；這裡只鏡像它來決定對話框顯示什麼、停用什麼。
 * 使用者打的值不是數字時原樣送給伺服器（由伺服器說明原因）。透過 HTTP 永遠不送資料夾（XP16）。
 *
 * 資料怎麼流：ExportDialog 的表單值 → `settingsFromForm` → POST /api/export（`exportRequest`）；
 * 上次用的設定記在 localStorage `darkroom.exportSettings`，讀回時用 `exportSettingsFrom` 修正。
 */
import { zh, type Translate } from './text';

export type ExportFormat = 'jpeg' | 'png' | 'tiff' | 'webp';
export type ResizeMode = 'long_edge' | 'short_edge' | 'width' | 'height' | 'megapixels' | 'percent';
export type Metadata = 'all' | 'copyright' | 'none';
export type SharpenTarget = 'screen' | 'matte' | 'glossy';
export type SharpenAmount = 'low' | 'standard' | 'high';

/** 使用者打的值可能不是數字：原樣送出，由伺服器判。 */
type NumOrText = number | string;

/** 匯出設定：伺服器接受的 8 個鍵（不含資料夾）。 */
export interface ExportSettings {
  format: ExportFormat | string;
  bit_depth: NumOrText | null;
  quality: NumOrText | null;
  max_kb: NumOrText | null;
  resize: { mode: ResizeMode | string; value: NumOrText } | null;
  metadata: Metadata | string;
  remove_gps: boolean;
  sharpen: { target: SharpenTarget | string; amount: SharpenAmount | string } | null;
}

/** 匯出預設：具名的一組匯出設定（存在 data_dir/export-presets.json）。 */
export interface ExportPreset {
  name: string;
  settings: ExportSettings;
}

/** 一張的匯出結果（POST /api/export 的 results）。ExportFile＝成功時寫出的新檔。 */
export interface ExportFile {
  ok: boolean;
  source: string;
  output?: string;
  error?: string;
  used?: { params_from: 'edit' | 'original' | 'request'; quality?: number | null; width: number; height: number };
}

/** 對話框表單的原始值（都是字串或勾選）。 */
export interface ExportForm {
  format: string;
  bit_depth?: string | number;
  quality?: string | number | null;
  max_kb_on?: boolean;
  max_kb?: string | number;
  resize_mode?: string;
  resize_value?: string | number;
  metadata?: string;
  remove_gps?: boolean;
  sharpen_target?: string;
  sharpen_amount?: string;
}

export const EXPORT_SETTINGS_KEY = 'darkroom.exportSettings';
export const EXPORT_FORMATS: readonly ExportFormat[] = ['jpeg', 'png', 'tiff', 'webp'];
export const FORMAT_LABELS: Record<ExportFormat, string> = { jpeg: 'JPEG', png: 'PNG', tiff: 'TIFF', webp: 'WebP' };
export const RESIZE_MODES: readonly ResizeMode[] = ['long_edge', 'short_edge', 'width', 'height', 'megapixels', 'percent'];
export const METADATA_MODES: readonly Metadata[] = ['all', 'copyright', 'none'];
export const SHARPEN_TARGETS: readonly SharpenTarget[] = ['screen', 'matte', 'glossy'];
export const SHARPEN_AMOUNTS: readonly SharpenAmount[] = ['low', 'standard', 'high'];

const labels = <K extends string>(keys: readonly K[], prefix: string): Record<K, string> =>
  Object.fromEntries(keys.map((k) => [k, zh(`${prefix}.${k}`)])) as Record<K, string>;
export const RESIZE_LABELS = labels(RESIZE_MODES, 'export.resizeModes');
export const METADATA_LABELS = labels(METADATA_MODES, 'export.metadataModes');
export const SHARPEN_TARGET_LABELS = labels(SHARPEN_TARGETS, 'export.sharpenTargets');
export const SHARPEN_AMOUNT_LABELS = labels(SHARPEN_AMOUNTS, 'export.sharpenAmounts');
export const REMOVE_GPS_LABEL = zh('export.removeGps');
export const NO_RESIZE_LABEL = zh('export.noResize');
export const NO_SHARPEN_LABEL = zh('export.noSharpen');
export const ORIGINAL_SIZE = zh('export.originalSize');
export const CUSTOM_PRESET = zh('export.custom');
export const UNDO_LABEL = zh('common.undo');
export const EXPORT_PRESET_NAME_PROMPT = zh('export.presetNamePrompt');
export const EXPORT_BUSY = zh('export.busy');
export const EXPORT_DEFAULT_QUALITY = 92;

export const EXPORT_DEFAULTS: ExportSettings = {
  format: 'jpeg',
  bit_depth: 8,
  quality: 92,
  max_kb: null,
  resize: null,
  metadata: 'all',
  remove_gps: false,
  sharpen: null,
};

export const defaultBitDepth = (format: string): number => (format === 'tiff' ? 16 : 8);
/** 有品質設定的格式（JPEG／WebP）。 */
export const lossy = (format: string): boolean => format === 'jpeg' || format === 'webp';

export const exportDone = (outputPath: string, t: Translate = zh) => t('export.done', { path: outputPath });
export const exportFailed = (fileName: string, reason: string, t: Translate = zh) =>
  t('export.failed', { file: fileName, reason });
export const exportPresetSaved = (name: string, t: Translate = zh) => t('export.presetSaved', { name });
export const exportPresetUpdated = (name: string, t: Translate = zh) => t('export.presetUpdated', { name });
export const exportPresetDeleted = (name: string, t: Translate = zh) => t('export.presetDeleted', { name });

/** X13 舊版的單張匯出請求內容（目前畫面用 exportRequest；這個留給測試與相容）。 */
export function exportBody(
  req: { image_id: string; preset_id: string | null; strength: number; overrides: Record<string, number> },
  format: string,
  qualityText?: string | number | null,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    items: [{ image_id: req.image_id, preset_id: req.preset_id, strength: req.strength, overrides: req.overrides }],
    format,
  };
  if (format === 'jpeg') {
    const t = String(qualityText == null ? '' : qualityText).trim();
    body.quality = t === '' ? EXPORT_DEFAULT_QUALITY : /^\d+$/.test(t) ? parseInt(t, 10) : t; // 伺服器判
  }
  return body;
}

/** results 的一筆 → 給人看的一句。 */
export const exportMessage = (result: ExportFile, t: Translate = zh): string =>
  result.ok ? exportDone(result.output ?? '', t) : (result.error ?? '');

/** E8 鏡像：伺服器會寫出的尺寸（只縮不放），輸入是轉正後的尺寸與縮放設定。 */
export function resizeTarget(w: number, h: number, resize: { mode: string; value: number } | null | undefined): [number, number] {
  if (!resize) return [w, h];
  const m = resize.mode;
  const v = resize.value;
  const scale: Record<string, number> = {
    long_edge: v / Math.max(w, h),
    short_edge: v / Math.min(w, h),
    width: v / w,
    height: v / h,
    megapixels: Math.sqrt((v * 1e6) / (w * h)),
    percent: v / 100,
  };
  const s = scale[m];
  if (s === undefined || !(s < 1)) return [w, h];
  const rnd = (x: number) => Math.max(1, Math.floor(x + 0.5));
  if (m === 'megapixels') return [Math.max(1, Math.floor(w * s)), Math.max(1, Math.floor(h * s))];
  if (m === 'percent') return [rnd(w * s), rnd(h * s)];
  if (m === 'width') return [v, rnd(h * s)];
  if (m === 'height') return [rnd(w * s), v];
  if (m === 'long_edge') return w >= h ? [v, rnd(h * s)] : [rnd(w * s), v];
  return w <= h ? [v, rnd(h * s)] : [rnd(w * s), v]; // short_edge
}

/** 純數字 → number；其他原樣（伺服器判）。 */
const numberOrText = (t: unknown): NumOrText => {
  const s = String(t == null ? '' : t).trim();
  return /^-?(\d+\.?\d*|\.\d+)$/.test(s) ? Number(s) : s;
};

/** 表單原始值 → 伺服器收的 8 個鍵（只放這個格式適用的值）。 */
export function settingsFromForm(f: ExportForm): ExportSettings {
  const format = f.format;
  const resize = f.resize_mode ? { mode: f.resize_mode, value: numberOrText(f.resize_value) } : null;
  const sharpen = f.sharpen_target ? { target: f.sharpen_target, amount: f.sharpen_amount || 'standard' } : null;
  return {
    format,
    bit_depth: lossy(format) ? 8 : numberOrText(f.bit_depth || defaultBitDepth(format)),
    quality: lossy(format)
      ? numberOrText(f.quality === '' || f.quality == null ? EXPORT_DEFAULTS.quality : f.quality)
      : null,
    max_kb: format === 'jpeg' && f.max_kb_on ? numberOrText(f.max_kb) : null,
    resize,
    metadata: f.metadata || 'all',
    remove_gps: (f.metadata || 'all') === 'all' && !!f.remove_gps,
    sharpen,
  };
}

/** localStorage（或匯出預設）裡的值 → 完整設定；讀不懂的鍵回預設。 */
export function exportSettingsFrom(stored: unknown): ExportSettings {
  let o: unknown = stored;
  if (typeof stored === 'string') {
    try {
      o = JSON.parse(stored);
    } catch {
      o = null;
    }
  }
  if (!o || typeof o !== 'object') return { ...EXPORT_DEFAULTS };
  const r = o as Record<string, unknown>;
  const format = (EXPORT_FORMATS as readonly unknown[]).includes(r.format) ? (r.format as string) : (EXPORT_DEFAULTS.format as string);
  const res = r.resize as { mode?: unknown; value?: unknown } | null | undefined;
  const okRes = !!res && (RESIZE_MODES as readonly unknown[]).includes(res.mode) && typeof res.value === 'number';
  const sh = r.sharpen as { target?: unknown; amount?: unknown } | null | undefined;
  const okSh =
    !!sh && (SHARPEN_TARGETS as readonly unknown[]).includes(sh.target) && (SHARPEN_AMOUNTS as readonly unknown[]).includes(sh.amount);
  const q = r.quality;
  return {
    format,
    bit_depth: lossy(format) ? 8 : r.bit_depth === 8 || r.bit_depth === 16 ? r.bit_depth : defaultBitDepth(format),
    quality: lossy(format)
      ? Number.isInteger(q) && (q as number) >= 1 && (q as number) <= 100
        ? (q as number)
        : (EXPORT_DEFAULTS.quality as number)
      : null,
    max_kb: format === 'jpeg' && Number.isInteger(r.max_kb) ? (r.max_kb as number) : null,
    resize: okRes ? { mode: res.mode as string, value: res.value as number } : null,
    metadata: Object.prototype.hasOwnProperty.call(METADATA_LABELS, r.metadata as string) ? (r.metadata as string) : 'all',
    remove_gps: r.remove_gps === true,
    sharpen: okSh ? { target: sh.target as string, amount: sh.amount as string } : null,
  };
}

/** GET /api/capabilities 的 features（這裡只用到 webp）。 */
export type CapabilityMap = Record<string, { available: boolean; reason?: string | null } | undefined>;

export interface ExportDialogState {
  quality: { disabled: boolean };
  bitDepth: { disabled: boolean; options: number[] };
  maxKbOn: { disabled: boolean };
  maxKb: { disabled: boolean };
  webp: { disabled: boolean; title: string };
  go: { disabled: boolean };
  resizeValue: { disabled: boolean; min: number; max: number; step: number };
  removeGps: { disabled: boolean };
  sharpenAmount: { disabled: boolean };
}

/** E29：對話框哪些控制項停用，只在這裡決定（caps＝能力偵測結果，或 null）。 */
export function exportDialogState(settings: ExportSettings, caps: CapabilityMap | null | undefined): ExportDialogState {
  const f = String(settings.format);
  const webp = caps && caps.webp && caps.webp.available === false ? caps.webp.reason || '' : null;
  const mode = settings.resize ? String(settings.resize.mode) : '';
  const range =
    mode === 'megapixels'
      ? { min: 0.01, max: 1000, step: 0.01 }
      : mode === 'percent'
        ? { min: 0.01, max: 100, step: 0.01 }
        : { min: 1, max: 65535, step: 1 };
  return {
    quality: { disabled: !lossy(f) },
    bitDepth: { disabled: lossy(f), options: lossy(f) ? [8] : [8, 16] },
    maxKbOn: { disabled: f !== 'jpeg' },
    maxKb: { disabled: f !== 'jpeg' || settings.max_kb == null },
    webp: { disabled: webp !== null, title: webp || '' },
    go: { disabled: f === 'webp' && webp !== null },
    resizeValue: { disabled: !mode, ...range },
    removeGps: { disabled: settings.metadata !== 'all' },
    sharpenAmount: { disabled: !settings.sharpen },
  };
}

/** E29：一行摘要，例如「JPEG 品質 92 ・長邊 2048 px ・全部中繼資料 ・螢幕銳利化（標準）」。 */
export function exportSummary(s: ExportSettings, t: Translate = zh): string {
  const parts: string[] = [];
  const fmt = String(s.format);
  const fl = FORMAT_LABELS[fmt as ExportFormat] || fmt;
  parts.push(
    lossy(fmt)
      ? t('export.summary.quality', { format: fl, quality: s.quality == null ? EXPORT_DEFAULTS.quality : s.quality })
      : t('export.summary.bits', { format: fl, bits: s.bit_depth == null ? defaultBitDepth(fmt) : s.bit_depth }),
  );
  if (fmt === 'jpeg' && s.max_kb != null) parts.push(t('export.summary.maxKb', { kb: s.max_kb }));
  if (!s.resize) parts.push(t('export.originalSize'));
  else if (s.resize.mode === 'megapixels') parts.push(t('export.summary.megapixels', { value: s.resize.value }));
  else if (s.resize.mode === 'percent') parts.push(t('export.summary.percent', { value: s.resize.value }));
  else {
    const mode = String(s.resize.mode);
    const label = (RESIZE_MODES as readonly string[]).includes(mode) ? t(`export.resizeModes.${mode}`) : mode;
    parts.push(t('export.summary.pixels', { mode: label, value: s.resize.value }));
  }
  const meta = String(s.metadata);
  const metaLabel = (METADATA_MODES as readonly string[]).includes(meta) ? t(`export.metadataModes.${meta}`) : meta;
  parts.push(metaLabel + (meta === 'all' && s.remove_gps ? t('export.summary.gps', { label: t('export.removeGps') }) : ''));
  if (s.sharpen) {
    const tg = String(s.sharpen.target);
    const am = String(s.sharpen.amount);
    parts.push(
      t('export.summary.sharpen', {
        target: (SHARPEN_TARGETS as readonly string[]).includes(tg) ? t(`export.sharpenTargets.${tg}`) : tg,
        amount: (SHARPEN_AMOUNTS as readonly string[]).includes(am) ? t(`export.sharpenAmounts.${am}`) : am,
      }),
    );
  }
  return parts.join(t('export.summary.separator'));
}

/** 兩組設定說的是同一件事（鍵順序、缺鍵與 null 不計）。 */
export function sameSettings(a: Partial<ExportSettings> | null | undefined, b: Partial<ExportSettings> | null | undefined): boolean {
  const canon = (v: unknown): unknown =>
    v === undefined
      ? null
      : v !== null && typeof v === 'object'
        ? Object.keys(v)
            .sort()
            .map((k) => [k, canon((v as Record<string, unknown>)[k])])
        : v;
  const keys = Object.keys(EXPORT_DEFAULTS) as Array<keyof ExportSettings>;
  return JSON.stringify(keys.map((k) => canon(a && a[k]))) === JSON.stringify(keys.map((k) => canon(b && b[k])));
}

/** POST /api/export：項目＋8 個設定鍵；透過 HTTP 永遠不送資料夾（XP16）。 */
export const exportRequest = <I>(items: I[], settings: ExportSettings): { items: I[] } & ExportSettings => ({
  items,
  ...settings,
});

/** ExportSettings → 對話框表單值（fillDialog）。 */
export function exportFormFromSettings(s: ExportSettings, previous?: Partial<ExportForm>): Required<ExportForm> {
  const fmt = String(s.format);
  return {
    format: fmt,
    bit_depth: String(s.bit_depth == null ? defaultBitDepth(fmt) : s.bit_depth),
    quality: s.quality != null ? String(s.quality) : String(previous?.quality ?? EXPORT_DEFAULT_QUALITY),
    max_kb_on: s.max_kb != null,
    max_kb: s.max_kb != null ? String(s.max_kb) : String(previous?.max_kb ?? 800),
    resize_mode: s.resize ? String(s.resize.mode) : '',
    resize_value: s.resize ? String(s.resize.value) : String(previous?.resize_value ?? 2048),
    metadata: String(s.metadata),
    remove_gps: !!s.remove_gps,
    sharpen_target: s.sharpen ? String(s.sharpen.target) : '',
    sharpen_amount: s.sharpen ? String(s.sharpen.amount) : 'standard',
  };
}
