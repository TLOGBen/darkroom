/**
 * 設定與能力 context：設定（Settings）的型別與前端驗證、匯入設定時的差異、能力偵測（Capability）的句子。
 *
 * 設定的 API 形狀照 docs/architecture/plan-v2.md §3：
 *   GET  /api/settings          → {settings, defaults, sources: {鍵: "file"|"env"|"cli"|"default"}, config_file}
 *   PUT  /api/settings          → 部分更新；全部驗證通過才寫；回 {settings, applied: [鍵], pending_restart: [鍵],
 *                                 checks: {comfyui, agent_sdk, …}}（被命令列固定的鍵寫進檔案、但下次啟動才生效）
 *   GET  /api/settings/export   → {format: "darkroom-settings/1", version, settings}
 *   POST /api/settings/import   → 同 PUT 的驗證與套用
 *   GET  /api/version           → {version, python, torch, cuda, platform}
 * 真正的驗證在後端（domain/settings.py）；前端這裡只做「明顯不對就先別送」的檢查（例如金鑰欄不是 op:// 參照），
 * 後端錯誤句子照原句顯示在對應欄位。
 *
 * 能力（capabilities）的句子從舊 logic.js 移植（S2 E22、E23、E30），v2 加了 comfyui、agent_sdk 兩項（plan §3）。
 */
import { zh, type Translate } from './text';

/**
 * 設定（全部可選；沒寫就用預設）。API 用扁平的點號鍵（後端 darkroom_app/domain/settings.py：
 * "The API uses flat dotted names"），檔案裡 agent.* 才巢狀；所以前端一律用扁平鍵。
 * AgentSettings（darkroom 自己呼叫 Claude 用的設定）＝ agent.api_key_ref、agent.model、agent.budget_usd；
 * ComfyUIConnection＝ comfyui_url、comfyui_root。
 */
export type Settings = Partial<Record<string, string | number | null>>;
export type AgentSettings = Pick<Settings, 'agent.api_key_ref' | 'agent.model' | 'agent.budget_usd'>;
export type ComfyUIConnection = Pick<Settings, 'comfyui_url' | 'comfyui_root'>;

/** 值從哪來：設定檔、環境變數、命令列（--preset-dir／--data-dir，這次執行期間固定）、預設值。 */
export type SettingSource = 'file' | 'env' | 'cli' | 'default';

/** GET /api/settings。sources 的鍵是扁平的（巢狀鍵寫成 agent.model）。 */
export interface SettingsResponse {
  settings: Settings;
  defaults: Settings;
  sources: Record<string, SettingSource>;
  config_file: string | null;
}

/** 一項重測的結果（PUT 的 checks、capabilities 的每一項）。 */
export interface Capability {
  available: boolean;
  reason?: string | null;
}

/** PUT /api/settings 的回應。 */
export interface SettingsApplyResult {
  settings: Settings;
  applied: string[];
  /** 寫進設定檔了，但這次執行被命令列（--preset-dir／--data-dir）固定，下次不帶旗標啟動才生效的鍵。 */
  pending_restart?: string[];
  checks: Record<string, Capability>;
}

/** GET /api/settings/export。 */
export interface SettingsExport {
  format: 'darkroom-settings/1' | string;
  version?: string;
  settings: Settings;
}

/** GET /api/version。 */
export interface VersionInfo {
  version: string;
  python?: string | null;
  torch?: string | null;
  cuda?: string | null;
  platform?: string | null;
}

export const LANGUAGES = ['zh-TW', 'en-US'] as const;
export type Language = (typeof LANGUAGES)[number];
export const SETTINGS_FORMAT = 'darkroom-settings/1';

/** 設定頁上的欄位（扁平鍵）：分區、型別。順序就是畫面順序。 */
export const SETTING_FIELDS = [
  { key: 'language', section: 'general', kind: 'language' },
  { key: 'preset_dir', section: 'folders', kind: 'path' },
  { key: 'preset_library_dir', section: 'folders', kind: 'path' },
  { key: 'data_dir', section: 'folders', kind: 'path' },
  { key: 'localllms_root', section: 'folders', kind: 'path' },
  { key: 'calibration_sources_dir', section: 'folders', kind: 'path' },
  { key: 'agent.api_key_ref', section: 'agent', kind: 'secretRef' },
  { key: 'agent.model', section: 'agent', kind: 'text' },
  { key: 'agent.budget_usd', section: 'agent', kind: 'number' },
  { key: 'comfyui_url', section: 'comfyui', kind: 'url' },
  { key: 'comfyui_root', section: 'comfyui', kind: 'path' },
] as const;
export type SettingKey = (typeof SETTING_FIELDS)[number]['key'];
export type SettingSection = (typeof SETTING_FIELDS)[number]['section'];

/** 表單：每個扁平鍵一個字串（數字也先當字串，送出前轉）。 */
export type SettingsForm = Record<SettingKey, string>;

/** 設定的一個扁平鍵的值（API 本來就是扁平鍵；舊資料萬一是巢狀的 agent 物件也讀得到）。 */
export function getSetting(s: Settings | null | undefined, key: string): unknown {
  if (!s) return undefined;
  if (key in s) return s[key];
  const [a, b] = key.split('.');
  const top = (s as Record<string, unknown>)[a];
  return b !== undefined && top && typeof top === 'object' ? (top as Record<string, unknown>)[b] : undefined;
}

/** 設定 → 表單字串（null／undefined → ''）。 */
export function formFromSettings(s: Settings | null | undefined): SettingsForm {
  const out = {} as SettingsForm;
  for (const f of SETTING_FIELDS) {
    const v = getSetting(s, f.key);
    out[f.key] = v == null ? '' : String(v);
  }
  return out;
}

/** 一個欄位的表單字串 → 要送的值（空字串＝null，代表「用預設」；數字欄是純數字就轉 number，否則原樣讓後端說原因）。 */
function valueOf(kind: string, text: string): unknown {
  const t = text.trim();
  if (t === '') return null;
  if (kind === 'number') return /^-?(\d+\.?\d*|\.\d+)$/.test(t) ? Number(t) : t;
  return t;
}

/**
 * 只送有改的鍵（部分更新，plan §3）：比較表單與目前設定，回扁平鍵的 Settings 物件（null＝回到預設）。
 * 沒有任何改變時回空物件。
 */
export function settingsPatch(form: SettingsForm, current: Settings | null | undefined): Settings {
  const patch: Record<string, unknown> = {};
  for (const f of SETTING_FIELDS) {
    const next = valueOf(f.kind, form[f.key]);
    const now = getSetting(current, f.key);
    if ((now ?? null) === next) continue;
    if (now != null && next != null && String(now) === String(next)) continue;
    patch[f.key] = next;
  }
  return patch as Settings;
}

/** 1Password 參照的形狀：op://<vault>/<item>/<field>（再多層也接受）。 */
export const isSecretRef = (v: string): boolean => /^op:\/\/[^/\s]+\/[^/\s]+\/[^\s]+$/.test(v.trim());

/** loopback 位址（plan §3：comfyui_url 只接受本機）。 */
export function isLoopbackUrl(v: string): boolean {
  try {
    const u = new URL(v.trim());
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
    const h = u.hostname.replace(/^\[|\]$/g, '');
    return h === '127.0.0.1' || h === 'localhost' || h === '::1';
  } catch {
    return false;
  }
}

/** 送出前的前端檢查：回 {扁平鍵: 給人看的句子}；空物件＝可以送。真正的規則在後端。 */
export function validateForm(form: SettingsForm, t: Translate = zh): Partial<Record<SettingKey, string>> {
  const errors: Partial<Record<SettingKey, string>> = {};
  const ref = form['agent.api_key_ref'].trim();
  if (ref && !isSecretRef(ref)) errors['agent.api_key_ref'] = t('settings.errors.secretRef');
  const budget = form['agent.budget_usd'].trim();
  if (budget && !(/^\d+(\.\d+)?$/.test(budget) && Number(budget) > 0)) errors['agent.budget_usd'] = t('settings.errors.budget');
  const url = form.comfyui_url.trim();
  if (url && !isLoopbackUrl(url)) errors.comfyui_url = t('settings.errors.loopback');
  return errors;
}

/**
 * 後端的錯誤句子 → 是哪個欄位的。後端句子目前是原句（多半含鍵名，例如「preset_dir：找不到資料夾」），
 * 找到第一個出現在句子裡的鍵就歸給它（較長的鍵先比，避免 preset_dir 搶走 preset_library_dir）；都沒有回 null（顯示在頁面頂端）。
 */
export function fieldOfError(message: string): SettingKey | null {
  // 「不認得的設定鍵：x（可用 a、b、c…）」會列出所有鍵，不歸給任何一欄
  if (/^不認得的設定鍵|unknown setting/i.test(message)) return null;
  const keys = [...SETTING_FIELDS.map((f) => f.key)].sort((a, b) => b.length - a.length);
  for (const k of keys) {
    const short = k.includes('.') ? k.split('.')[1] : k;
    if (message.includes(k)) return k;
    if (k.includes('.') && new RegExp(`\\b${short}\\b`).test(message)) return k;
  }
  if (/anthropic_api_key_ref/.test(message)) return 'agent.api_key_ref';
  if (/semantic_index_budget_usd/.test(message)) return 'agent.budget_usd';
  return null;
}

/** 匯入設定前的差異：哪些扁平鍵會從什麼改成什麼。 */
export interface SettingsDiffRow {
  key: string;
  from: unknown;
  to: unknown;
}

/** 攤平成 {扁平鍵: 值}（API 已是扁平；舊式巢狀的 agent 物件也攤開）。 */
export function flattenSettings(s: Settings | null | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(s || {})) {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      for (const [k2, v2] of Object.entries(v as Record<string, unknown>)) out[`${k}.${k2}`] = v2;
    } else out[k] = v;
  }
  return out;
}

/** 匯入檔的設定與目前設定的差異（依鍵名排序；值相同的不列）。 */
export function settingsDiff(current: Settings | null | undefined, incoming: Settings | null | undefined): SettingsDiffRow[] {
  const a = flattenSettings(current);
  const b = flattenSettings(incoming);
  const rows: SettingsDiffRow[] = [];
  for (const key of Object.keys(b).sort()) {
    if (JSON.stringify(a[key] ?? null) !== JSON.stringify(b[key] ?? null)) rows.push({ key, from: a[key] ?? null, to: b[key] ?? null });
  }
  return rows;
}

/** 讀匯入檔：格式不對回 null（後端會再驗一次，未知鍵與格式不對整份不寫）。 */
export function parseSettingsFile(text: string): SettingsExport | null {
  try {
    const o = JSON.parse(text) as unknown;
    if (!o || typeof o !== 'object') return null;
    const r = o as Record<string, unknown>;
    if (r.format !== SETTINGS_FORMAT || !r.settings || typeof r.settings !== 'object') return null;
    return { format: SETTINGS_FORMAT, version: typeof r.version === 'string' ? r.version : undefined, settings: r.settings as Settings };
  } catch {
    return null;
  }
}

/**
 * 使用者「真的設定過」的介面語言；沒設定過回 null。
 *
 * GET /api/settings 會把預設值合併進 settings：沒設 language 時也回 "zh-TW"（sources.language 是 "default"）。
 * 那個 zh-TW 不是使用者選的，拿來切語言會蓋掉 plan §2 的「瀏覽器語言」與上次記住的語言，所以只認來源不是
 * default 的值（設定檔、環境變數…）。回 null 時呼叫端保持目前語言（一開始就是 pickLanguage(記住的, 瀏覽器)）。
 */
export function configuredLanguage(res: Pick<SettingsResponse, 'settings' | 'sources'> | null | undefined): Language | null {
  if (!res || !res.sources || res.sources.language === 'default' || !res.sources.language) return null;
  const lang = getSetting(res.settings, 'language');
  return (LANGUAGES as readonly unknown[]).includes(lang) ? (lang as Language) : null;
}

/** 預設語言：設定 → 瀏覽器語言 → zh-TW（plan §2）。 */
export function pickLanguage(setting: unknown, browser: readonly string[] | null | undefined): Language {
  if ((LANGUAGES as readonly unknown[]).includes(setting)) return setting as Language;
  for (const b of browser || []) {
    const l = b.toLowerCase();
    if (l.startsWith('zh')) return 'zh-TW';
    if (l.startsWith('en')) return 'en-US';
  }
  return 'zh-TW';
}

// ---------------------------------------------------------------------------------------------------------------------
// 能力（S2 E22、E23、E30；v2 加 comfyui、agent_sdk）
// ---------------------------------------------------------------------------------------------------------------------

export const CAP_ORDER = [
  'gpu',
  'heic',
  'webp',
  'photo_library',
  'preset_library_writes',
  'semantic_index',
  'onepassword',
  'comfyui',
  'agent_sdk',
] as const;
export type CapabilityKey = (typeof CAP_ORDER)[number];
export type Capabilities = Partial<Record<string, Capability>>;

export const CAP_LABELS: Record<CapabilityKey, string> = Object.fromEntries(
  CAP_ORDER.map((k) => [k, zh(`caps.labels.${k}`)]),
) as Record<CapabilityKey, string>;
export const CAP_OK = zh('caps.ok');
export const CAP_AVAILABLE = zh('caps.available');
export const CAP_REFRESH = zh('caps.refresh');

export const capStatus = (n: number, t: Translate = zh) => t('caps.status', { n });
/** 關閉的能力（照固定順序）。 */
export const capOff = (features: Capabilities | null | undefined): CapabilityKey[] =>
  CAP_ORDER.filter((k) => features && features[k] && features[k]!.available === false);
export const capButtonText = (features: Capabilities | null | undefined, t: Translate = zh): string => {
  const n = capOff(features).length;
  return n ? capStatus(n, t) : t('caps.ok');
};
const capLabel = (key: string, t: Translate) => ((CAP_ORDER as readonly string[]).includes(key) ? t(`caps.labels.${key}`) : key);
export const capLine = (key: string, f: Capability | null | undefined, t: Translate = zh): string =>
  t('caps.line', {
    label: capLabel(key, t),
    state: f && f.available ? t('caps.available') : t('caps.off', { reason: (f && f.reason) || '' }),
  });
/** 某個能力關閉的原因，或 null（不知道的能力當作開著：頁面永遠不因為缺答案而擋住）。 */
export const capReason = (features: Capabilities | null | undefined, key: string): string | null =>
  features && features[key] && features[key]!.available === false ? features[key]!.reason || '' : null;
