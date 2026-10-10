/**
 * 設定頁（路由 /settings，頂列有入口）：單欄表單、左對齊、最寬 720px（DESIGN.md §6.7）。
 *
 * 分區：一般（語言即時切換、外觀）、資料夾、AI 代理（Claude Agent SDK）、ComfyUI、匯入／匯出設定、關於。
 * 資料怎麼流（plan-v2 §3）：
 *   GET /api/settings → 表單（每欄旁邊寫來源：設定檔／環境變數／預設值；來自環境變數的欄位唯讀）
 *   按「套用」→ 前端先擋明顯不對的（金鑰欄不是 op:// 參照…）→ PUT /api/settings（只送有改的鍵）
 *     → 成功：顯示每項重測結果（checks），所有伺服器資料失效重讀（設定改了資料夾，preset 列表等都會變），立即生效
 *     → 失敗：後端錯誤原句顯示在對應欄位（找不到欄位就顯示在頁首）。
 *   匯出：GET /api/settings/export 存成 JSON 檔；匯入：讀 JSON → 先列出會改哪些鍵 → 確認後 POST /api/settings/import。
 * 金鑰：只收 1Password 參照，畫面明寫「金鑰不會存進設定檔」；永遠不顯示金鑰值（後端也不會回）。
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormHelperText,
  LinearProgress,
  MenuItem,
  Select,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useColorScheme,
} from '@mui/material';
import clsx from 'clsx';
import {
  LANGUAGES,
  SETTING_FIELDS,
  configuredLanguage,
  fieldOfError,
  formFromSettings,
  getSetting,
  parseSettingsFile,
  settingsDiff,
  settingsPatch,
  validateForm,
  type Capability,
  type Language,
  type SettingKey,
  type SettingSection,
  type SettingsExport,
  type SettingsForm,
} from '../domain/settings';
import { explain } from '../domain/errors';
import { ApiError } from '../middlewares';
import * as settingsReq from '../requests/settings';
import { invalidateAfterSettings, useCapabilities, useSettings, useVersion } from '../hooks/queries';
import { toast } from '../hooks/useAppStore';
import { useT } from '../hooks/useT';
import { setLanguage } from '../i18n';
import { readText, saveBlob } from '../utils/files';
import css from './SettingsPage.module.scss';

type FieldErrors = Partial<Record<SettingKey, string>>;

/** 重測項目 → 顯示在哪一欄底下。 */
const CHECK_FIELD: Record<string, SettingKey> = {
  comfyui: 'comfyui_url',
  agent_sdk: 'agent.api_key_ref',
  onepassword: 'agent.api_key_ref',
  preset_library_writes: 'preset_library_dir',
  photo_library: 'data_dir',
};

export function SettingsPage() {
  const t = useT();
  const q = useSettings();
  const version = useVersion();
  const { data: caps } = useCapabilities();
  const { mode, setMode } = useColorScheme();
  const [form, setForm] = useState<SettingsForm | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [topError, setTopError] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, Capability> | null>(null);
  const [busy, setBusy] = useState(false);
  const [importDoc, setImportDoc] = useState<{ name: string; doc: SettingsExport } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const current = q.data?.settings;
  // 第一次讀到（或套用後重讀）就填表單
  useEffect(() => {
    if (q.data) setForm(formFromSettings(q.data.settings));
  }, [q.data]);
  // 設定裡的語言 → 介面語言（設定 → 瀏覽器 → zh-TW）
  useEffect(() => {
    // 只有使用者真的設定過才切（沒設定時後端回的 zh-TW 是預設值，不能蓋掉瀏覽器語言／上次記住的語言）
    const lang = configuredLanguage(q.data);
    if (lang) setLanguage(lang);
  }, [q.data]);

  const emptyForm = useMemo(() => formFromSettings(null), []);
  const f = form ?? emptyForm;
  const patch = useMemo(() => (form ? settingsPatch(form, current) : {}), [form, current]);
  const dirty = Object.keys(patch).length > 0;
  const unavailable = q.error ? (q.error as Error).message : null;

  const setField = (key: SettingKey, value: string) => {
    setForm((old) => ({ ...(old ?? emptyForm), [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  };

  const showError = (e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    const field = fieldOfError(msg);
    if (field) setErrors((old) => ({ ...old, [field]: msg }));
    else setTopError(msg);
  };

  const apply = async () => {
    if (!form) return;
    setTopError(null);
    setChecks(null);
    const local = validateForm(form, t);
    setErrors(local);
    if (Object.keys(local).length) return;
    if (!dirty) {
      toast(t('settings.nothingChanged'));
      return;
    }
    setBusy(true);
    try {
      const res = await settingsReq.putSettings(patch);
      setChecks(res.checks ?? {});
      await invalidateAfterSettings(); // 立即生效：preset 庫、滑桿、能力都重讀
      toast(t('settings.applied', { n: res.applied?.length ?? Object.keys(patch).length }));
      // 被命令列固定的鍵：寫進檔案了，但這次執行還是用命令列的值（不要讓人以為已經換了資料夾）
      if (res.pending_restart?.length) toast(t('settings.pendingRestart', { keys: res.pending_restart.join('、') }));
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  };

  const doExport = async () => {
    try {
      const doc = await settingsReq.exportSettings();
      saveBlob('darkroom-settings.json', new Blob([JSON.stringify(doc, null, 2) + '\n'], { type: 'application/json' }));
    } catch (e) {
      toast(explain((e as Error).message, t), true, (e as Error).message);
    }
  };

  const pickImport = async (file: File | undefined) => {
    if (!file) return;
    const doc = parseSettingsFile(await readText(file));
    if (!doc) {
      toast(t('settings.transfer.badFile'), true);
      return;
    }
    setImportDoc({ name: file.name, doc });
  };

  const applyImport = async () => {
    if (!importDoc) return;
    setBusy(true);
    setTopError(null);
    try {
      const res = await settingsReq.importSettings(importDoc.doc);
      setChecks(res.checks ?? {});
      setImportDoc(null);
      await invalidateAfterSettings();
      toast(t('settings.transfer.imported', { n: res.applied?.length ?? 0 }));
    } catch (e) {
      setImportDoc(null);
      showError(e);
    } finally {
      setBusy(false);
    }
  };

  const source = (key: string) => q.data?.sources?.[key];
  const fromEnv = (key: string) => source(key) === 'env';
  const checksFor = (key: SettingKey) =>
    Object.entries(checks ?? {}).filter(([k]) => CHECK_FIELD[k] === key || k === key);
  const otherChecks = Object.entries(checks ?? {}).filter(([k]) => !CHECK_FIELD[k] && !SETTING_FIELDS.some((x) => x.key === k));

  /** 一列：標籤（160px）｜控制項｜來源；底下說明、錯誤原句、重測結果。 */
  const field = (key: SettingKey, control: ReactNode, extra?: ReactNode) => {
    const err = errors[key];
    const src = source(key);
    const def = getSetting(q.data?.defaults, key);
    return (
      <div className={css.row} key={key}>
        <label className={css.label} htmlFor={`set-${key}`}>
          {t(`settings.fields.${key}`)}
        </label>
        <div className={css.ctl}>
          {control}
          <FormHelperText error={!!err} className={css.help}>
            {err ??
              (fromEnv(key)
                ? t('settings.envReadOnly')
                : src === 'cli'
                  ? t('settings.cliPinned')
                  : t(`settings.help.${key}`))}
          </FormHelperText>
          {def != null && def !== '' && !err && src !== 'default' && <FormHelperText className={css.help}>{t('settings.defaultValue', { value: String(def) })}</FormHelperText>}
          {extra}
          {checksFor(key).map(([k, c]) => (
            <CheckLine key={k} name={k} check={c} />
          ))}
        </div>
        <span className={css.source}>{src ? t(`settings.source.${src}`) : ''}</span>
      </div>
    );
  };

  const textField = (key: SettingKey, opts: { mono?: boolean; placeholder?: string } = {}) =>
    field(
      key,
      <TextField
        id={`set-${key}`}
        fullWidth
        value={f[key]}
        error={!!errors[key]}
        disabled={fromEnv(key) || !form}
        placeholder={opts.placeholder ?? String(getSetting(q.data?.defaults, key) ?? '')}
        onChange={(e) => setField(key, e.target.value)}
        slotProps={{ htmlInput: { spellCheck: false, className: opts.mono ? 'dr-mono' : undefined } }}
      />,
    );

  const section = (s: SettingSection) => SETTING_FIELDS.filter((x) => x.section === s);
  const agentCap = caps?.agent_sdk;
  const comfyCap = caps?.comfyui;

  return (
    <div className={css.page}>
      <div className={css.inner}>
        <Typography variant="h1">{t('settings.title')}</Typography>
        <p className={css.configFile}>
          {q.data?.config_file ? (
            <>
              {t('settings.configFileLabel')}
              <code className="dr-mono">{q.data.config_file}</code>
            </>
          ) : q.data ? (
            t('settings.configFileNone')
          ) : null}
        </p>
        {q.isLoading && <LinearProgress />}
        {unavailable && (
          <p className={css.topError} role="alert">
            {q.error instanceof ApiError && q.error.status === 404
              ? t('settings.unavailable', { reason: unavailable })
              : t('settings.loadFailed', { reason: unavailable })}
          </p>
        )}
        {topError && (
          <p className={css.topError} role="alert">
            {topError}
          </p>
        )}

        {/* ---- 一般 ---- */}
        <section className={css.section} aria-labelledby="sec-general">
          <Typography variant="h2" id="sec-general">
            {t('settings.sections.general')}
          </Typography>
          {field(
            'language',
            <Select
              id="set-language"
              value={f.language || 'zh-TW'}
              disabled={fromEnv('language')}
              onChange={(e) => {
                const lang = String(e.target.value) as Language;
                setField('language', lang);
                setLanguage(lang); // 即時切換；存進設定檔要按「套用」
              }}
            >
              {LANGUAGES.map((l) => (
                <MenuItem key={l} value={l}>
                  {t(`settings.languages.${l}`)}
                </MenuItem>
              ))}
            </Select>,
          )}
          <div className={css.row}>
            <span className={css.label}>{t('settings.theme')}</span>
            <div className={css.ctl}>
              <ToggleButtonGroup exclusive value={mode ?? 'dark'} onChange={(_, v) => v && setMode(v)} aria-label={t('settings.theme')}>
                {(['dark', 'light', 'system'] as const).map((m) => (
                  <ToggleButton key={m} value={m}>
                    {t(`settings.themes.${m}`)}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
            </div>
            <span className={css.source} />
          </div>
        </section>

        {/* ---- 資料夾 ---- */}
        <section className={css.section} aria-labelledby="sec-folders">
          <Typography variant="h2" id="sec-folders">
            {t('settings.sections.folders')}
          </Typography>
          {section('folders').map((x) => textField(x.key, { mono: true }))}
        </section>

        {/* ---- AI 代理 ---- */}
        <section className={css.section} aria-labelledby="sec-agent">
          <Typography variant="h2" id="sec-agent">
            {t('settings.sections.agent')}
          </Typography>
          {field(
            'agent.api_key_ref',
            <TextField
              id="set-agent.api_key_ref"
              fullWidth
              value={f['agent.api_key_ref']}
              error={!!errors['agent.api_key_ref']}
              disabled={fromEnv('agent.api_key_ref') || !form}
              placeholder="op://Private/Anthropic/credential"
              autoComplete="off"
              onChange={(e) => setField('agent.api_key_ref', e.target.value)}
              slotProps={{ htmlInput: { spellCheck: false, className: 'dr-mono' } }}
            />,
            <p className={css.keyNote}>{t('settings.keyNotStored')}</p>,
          )}
          {textField('agent.model', { mono: true })}
          {textField('agent.budget_usd')}
          <StatusRow label={t('settings.agentStatus')} cap={agentCap} />
        </section>

        {/* ---- ComfyUI ---- */}
        <section className={css.section} aria-labelledby="sec-comfy">
          <Typography variant="h2" id="sec-comfy">
            {t('settings.sections.comfyui')}
          </Typography>
          {textField('comfyui_url', { mono: true })}
          {textField('comfyui_root', { mono: true })}
          <StatusRow label={t('settings.comfyStatus')} cap={comfyCap} />
        </section>

        <div className={css.applyRow}>
          <Button variant="contained" disabled={busy || !form || !dirty} onClick={() => void apply()}>
            {busy ? t('settings.applying') : t('settings.apply')}
          </Button>
          {dirty && <span className={css.unsaved}>{t('settings.unsaved')}</span>}
          {otherChecks.map(([k, c]) => (
            <CheckLine key={k} name={k} check={c} />
          ))}
        </div>

        {/* ---- 匯入／匯出 ---- */}
        <section className={css.section} aria-labelledby="sec-transfer">
          <Typography variant="h2" id="sec-transfer">
            {t('settings.sections.transfer')}
          </Typography>
          <div className={css.transfer}>
            <Button variant="text" title={t('settings.transfer.exportTitle')} disabled={!!unavailable} onClick={() => void doExport()}>
              {t('settings.transfer.export')}
            </Button>
            <Button variant="text" title={t('settings.transfer.importTitle')} disabled={!!unavailable} onClick={() => fileRef.current?.click()}>
              {t('settings.transfer.import')}
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = '';
                void pickImport(file);
              }}
            />
          </div>
        </section>

        {/* ---- 關於 ---- */}
        <section className={css.section} aria-labelledby="sec-about">
          <Typography variant="h2" id="sec-about">
            {t('settings.sections.about')}
          </Typography>
          {version.error ? (
            <p className={css.topError}>{t('settings.about.loadFailed', { reason: (version.error as Error).message })}</p>
          ) : (
            <dl className={css.about}>
              {(['version', 'python', 'torch', 'cuda', 'platform'] as const).map((k) => (
                <div key={k}>
                  <dt>{t(`settings.about.${k}`)}</dt>
                  <dd className="dr-num">{version.data?.[k] ?? t('settings.about.unknown')}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </div>

      <ImportPreview
        open={!!importDoc}
        name={importDoc?.name ?? ''}
        rows={importDoc ? settingsDiff(current, importDoc.doc.settings) : []}
        busy={busy}
        onCancel={() => setImportDoc(null)}
        onApply={() => void applyImport()}
      />
    </div>
  );
}

/** 一項重測的結果：ok 點＋「可以連線」，或 err 點＋原因原句。 */
function CheckLine({ name, check }: { name: string; check: Capability }) {
  const t = useT();
  return (
    <p className={clsx(css.check, check.available ? css.ok : css.err)}>
      <i aria-hidden="true" />
      <span>
        {t(`caps.labels.${name}`, { defaultValue: name })}：
        {check.available ? (name === 'comfyui' ? t('settings.check.ok') : t('settings.check.okGeneric')) : (check.reason ?? '')}
      </span>
    </p>
  );
}

/** 「目前狀態／連線狀態」：能力偵測裡對應的那一項。 */
function StatusRow({ label, cap }: { label: string; cap: Capability | undefined }) {
  const t = useT();
  return (
    <div className={css.row}>
      <span className={css.label}>{label}</span>
      <div className={css.ctl}>
        {cap ? (
          <p className={clsx(css.check, cap.available ? css.ok : css.err)}>
            <i aria-hidden="true" />
            <span>{cap.available ? t('caps.available') : t('caps.off', { reason: cap.reason ?? '' })}</span>
          </p>
        ) : (
          <p className={css.check}>
            <i aria-hidden="true" />
            <span>{t('settings.statusUnknown')}</span>
          </p>
        )}
      </div>
      <span className={css.source} />
    </div>
  );
}

/** 匯入前的差異預覽：列出會改哪些鍵（目前 → 匯入後），確認才套用。 */
function ImportPreview(props: {
  open: boolean;
  name: string;
  rows: Array<{ key: string; from: unknown; to: unknown }>;
  busy: boolean;
  onCancel: () => void;
  onApply: () => void;
}) {
  const t = useT();
  const show = (v: unknown) => (v === null || v === undefined || v === '' ? t('common.none') : String(v));
  return (
    <Dialog open={props.open} onClose={props.onCancel} fullWidth>
      <DialogTitle>
        {t('settings.transfer.previewTitle')} <span className={css.dialogSub}>{props.name}</span>
      </DialogTitle>
      <DialogContent>
        {props.rows.length ? (
          <>
            <p className={css.diffHead}>{t('settings.transfer.previewHead', { n: props.rows.length })}</p>
            <table className={css.diff}>
              <thead>
                <tr>
                  <th />
                  <th>{t('settings.transfer.from')}</th>
                  <th>{t('settings.transfer.to')}</th>
                </tr>
              </thead>
              <tbody>
                {props.rows.map((r) => (
                  <tr key={r.key}>
                    <th className="dr-mono">{r.key}</th>
                    <td className="dr-mono">{show(r.from)}</td>
                    <td className="dr-mono">{show(r.to)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p>{t('settings.transfer.previewNone')}</p>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={props.onCancel}>{t('common.cancel')}</Button>
        <Button variant="contained" disabled={props.busy || !props.rows.length} onClick={props.onApply}>
          {t('settings.transfer.applyImport', { n: props.rows.length })}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

