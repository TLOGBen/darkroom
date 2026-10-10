/**
 * Preset 庫 context：preset 列表的型別、搜尋、樹狀分組、樹的鍵盤、匯入／下載的批次與報告句子。
 *
 * 從舊 logic.js 移植（R6 樹鍵盤與搜尋、K19 preset 庫、SI10 語意標籤、S2 E16／E30 下載 .xmp），只加型別。
 * 資料怎麼流：requests/presets.ts 拿到 GET /api/presets、/api/preset_flags、/api/preset-library/groups
 * → hooks/usePresets 包成 TanStack Query → components/presets/PresetTree 用本檔的 `buildTree`／`matchPreset` 畫樹。
 * 改名、搬移、最愛只寫 preset 庫的索引（library.json），買來的 .xmp 永遠不動。
 */
import { zh, type Translate } from './text';

/** preset 列表的一列（GET /api/presets）。 */
export interface Preset {
  id: string;
  name: string;
  group: string;
  supported: boolean;
  favorite?: boolean;
  /** 無法套用的設定（給人看的鍵名） */
  skipped?: string[];
  /** 語意標籤（中英文） */
  tags?: string[];
  file?: string;
}

/** 自存 preset：id 以 `user:` 開頭，存在 preset 庫的 user/。 */
export type UserPreset = Preset & { id: `user:${string}` };

/** 有略過設定的 preset：id → major／minor。 */
export type SkippedSetting = 'major' | 'minor';
export type PresetFlags = Record<string, SkippedSetting>;

/** 群組樹（GET /api/preset-library/groups）：明確建立的群組即使空的也會出現。 */
export interface PresetGroup {
  name: string;
  count?: number;
  children: Array<{ name: string; count?: number }>;
}
export interface PresetGroups {
  groups: PresetGroup[];
  ungrouped: number;
}

/** 語意標籤（建語意索引之後才有）。 */
export type SemanticTags = string[];

export const USER_GROUP = zh('presets.userGroup');
export const FAV_EMPTY = zh('presets.favEmpty');
/** KP4：每個請求的 base64 上限（伺服器 1 MiB body 限制以內）。 */
export const UPLOAD_BATCH_CHARS = 700000;
export const PRESET_IDS_MAX = 500; // E16：一個請求 1～500 個 id
export const DOWNLOAD_XMP = zh('presets.menu.download');
export const DOWNLOAD_GROUP_XMP = zh('presets.menu.downloadGroup');

export const presetSaved = (name: string, t: Translate = zh) => t('presets.saved', { name });
export const importSummary = (ok: number, fail: number, t: Translate = zh) => t('presets.importSummary', { ok, fail });
export const importedLine = (id: string, t: Translate = zh) => t('presets.importedLine', { id });
export const groupCreated = (group: string, t: Translate = zh) => t('presets.groupCreated', { group });
export const favMark = (fav: boolean | undefined): string => (fav ? '★' : '☆');
export const downloadSummary = (ok: number, fail: number, t: Translate = zh) => t('presets.downloadSummary', { ok, fail });
export const downloadedLine = (fileName: string, t: Translate = zh) => t('presets.downloadedLine', { fileName });
export const downloadTooMany = (n: number, t: Translate = zh) => t('presets.downloadTooMany', { n });

// ---------------------------------------------------------------------------------------------------------------------
// R6 搜尋＋SI10 語意標籤
// ---------------------------------------------------------------------------------------------------------------------

/** 名稱、群組、語意標籤（中英文）都比對；每個詞都要出現（不分大小寫）。 */
export function matchPreset(p: Pick<Preset, 'name' | 'group' | 'tags'>, query: string | null | undefined): boolean {
  const terms = String(query || '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  const hay = (p.name + ' ' + (p.group || '') + ' ' + (p.tags || []).join(' ')).toLowerCase();
  return terms.every((term) => hay.includes(term));
}

/** 列的提示：「群組 / 名稱｜標籤、標籤」。 */
export function presetTitle(p: Pick<Preset, 'name' | 'group' | 'tags'>): string {
  const base = p.group ? p.group + ' / ' + p.name : p.name;
  return p.tags && p.tags.length ? base + '｜' + p.tags.join('、') : base;
}

// ---------------------------------------------------------------------------------------------------------------------
// 樹：第一個「 - 」分上下層
// ---------------------------------------------------------------------------------------------------------------------

/** 沒有群組的 preset 放在這個鍵底下（顯示文字由畫面翻譯）。 */
export const UNGROUPED = '\u0002ungrouped';

/** '人物 - 女人' → ['人物', '女人']；沒有群組 → [UNGROUPED, null]。 */
export function splitGroup(group: string | null | undefined): [string, string | null] {
  const g = (group || '').trim();
  if (!g) return [UNGROUPED, null];
  const i = g.indexOf(' - ');
  return i < 0 ? [g, null] : [g.slice(0, i), g.slice(i + 3)];
}

export interface TreeTop {
  subs: Map<string, Preset[]>;
  items: Preset[];
}

/** 上層 → {子群組 → preset、直屬 preset}；K10：明確建立的群組即使空的也列出。 */
export function buildTree(presets: Preset[], libGroups: PresetGroups | null | undefined): Map<string, TreeTop> {
  const root = new Map<string, TreeTop>();
  for (const g of libGroups?.groups ?? []) {
    if (!root.has(g.name)) root.set(g.name, { subs: new Map(), items: [] });
    for (const c of g.children) {
      const node = root.get(g.name) as TreeTop;
      if (!node.subs.has(c.name)) node.subs.set(c.name, []);
    }
  }
  for (const p of presets) {
    const [top, sub] = splitGroup(p.group);
    if (!root.has(top)) root.set(top, { subs: new Map(), items: [] });
    const node = root.get(top) as TreeTop;
    if (sub === null) node.items.push(p);
    else {
      if (!node.subs.has(sub)) node.subs.set(sub, []);
      (node.subs.get(sub) as Preset[]).push(p);
    }
  }
  return root;
}

// ---------------------------------------------------------------------------------------------------------------------
// R6 樹的鍵盤
// ---------------------------------------------------------------------------------------------------------------------

/** 看得到的一列：資料夾或 preset，深度、是否展開、父列索引（-1＝沒有）。 */
export interface TreeRowMeta {
  type: 'folder' | 'preset';
  depth: number;
  open?: boolean;
  parent: number;
}

export interface TreeKeyResult {
  focus: number;
  action: 'apply' | 'toggle' | 'expand' | 'collapse' | null;
}

/** 方向鍵、Home／End、Enter 在樹裡的行為（WAI-ARIA tree pattern）。不是我們的鍵回 null。 */
export function treeKey(rows: TreeRowMeta[], i: number, key: string): TreeKeyResult | null {
  const n = rows.length;
  const row = rows[i];
  if (!row) return null;
  const at = (focus: number, action?: TreeKeyResult['action']): TreeKeyResult => ({ focus, action: action || null });
  switch (key) {
    case 'ArrowDown':
      return at(Math.min(i + 1, n - 1));
    case 'ArrowUp':
      return at(Math.max(i - 1, 0));
    case 'Home':
      return at(0);
    case 'End':
      return at(n - 1);
    case 'Enter':
      return at(i, row.type === 'preset' ? 'apply' : 'toggle');
    case 'ArrowRight':
      if (row.type !== 'folder') return at(i);
      if (!row.open) return at(i, 'expand');
      return at(i + 1 < n && rows[i + 1].depth > row.depth ? i + 1 : i);
    case 'ArrowLeft':
      if (row.type === 'folder' && row.open) return at(i, 'collapse');
      return at(row.parent >= 0 ? row.parent : i);
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------------------------------------------------
// K19 存成 preset、匯入；S2 下載 .xmp
// ---------------------------------------------------------------------------------------------------------------------

export interface SaveBody {
  name: string;
  group: string;
  preset_id: string | null;
  strength: number;
  overrides: Record<string, number>;
}

/** POST /api/preset-library/save：req 是目前編輯的預覽請求。 */
export function saveBody(
  req: { preset_id: string | null; strength: number; overrides: Record<string, number> },
  name: string,
  group?: string | null,
): SaveBody {
  return { name, group: group || USER_GROUP, preset_id: req.preset_id, strength: req.strength, overrides: req.overrides };
}

export interface UploadFile {
  name: string;
  data_base64: string;
}

/** 把上傳檔案分批：每批 base64 總長不超過 UPLOAD_BATCH_CHARS（單一檔案太大也自成一批，交給伺服器判）。 */
export function uploadBatches(files: UploadFile[]): UploadFile[][] {
  const out: UploadFile[][] = [];
  let cur: UploadFile[] = [];
  let size = 0;
  for (const f of files) {
    const n = f.data_base64.length + f.name.length;
    if (cur.length && size + n > UPLOAD_BATCH_CHARS) {
      out.push(cur);
      cur = [];
      size = 0;
    }
    cur.push(f);
    size += n;
  }
  if (cur.length) out.push(cur);
  return out;
}

export interface Report {
  summary: string;
  lines: string[];
}

/** 匯入結果：一行摘要＋每個檔一行（依原順序）。 */
export function importReport(
  results: Array<{ ok: boolean; id?: string; error?: string }>,
  t: Translate = zh,
): Report {
  const ok = results.filter((r) => r.ok).length;
  return {
    summary: importSummary(ok, results.length - ok, t),
    lines: results.map((r) => (r.ok ? importedLine(r.id ?? '', t) : (r.error ?? ''))),
  };
}

/** 一個請求最多 PRESET_IDS_MAX 個 id，多的分批。 */
export function idBatches(ids: string[]): string[][] {
  const out: string[][] = [];
  for (let i = 0; i < ids.length; i += PRESET_IDS_MAX) out.push(ids.slice(i, i + PRESET_IDS_MAX));
  return out;
}

/** 群組與底下每個子群組（「 - 」分層）的 preset id。 */
export function groupPresetIds(presets: Array<Pick<Preset, 'id' | 'group'>>, path: string): string[] {
  return presets
    .filter((p) => {
      const g = (p.group || '').trim();
      return g === path || g.startsWith(path + ' - ');
    })
    .map((p) => p.id);
}

export interface PresetFile {
  ok: boolean;
  preset_id: string;
  file_name?: string;
  data_base64?: string;
  error?: string;
}

/** 下載結果：一行摘要＋每個 preset 一行。 */
export function downloadReport(files: PresetFile[], t: Translate = zh): Report {
  const ok = files.filter((f) => f.ok).length;
  return {
    summary: downloadSummary(ok, files.length - ok, t),
    lines: files.map((f) => (f.ok ? downloadedLine(f.file_name ?? '', t) : (f.error ?? ''))),
  };
}
