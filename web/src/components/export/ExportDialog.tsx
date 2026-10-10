/**
 * 匯出對話框（S2 E29）：兩顆匯出鈕（預覽工具列的「匯出」、縮圖格的「匯出所選」）都打開它，填上次用的設定；
 * Enter 匯出、Esc 關閉、焦點鎖在對話框裡、關閉後焦點回到開它的按鈕（MUI Dialog 內建）。
 *
 * 欄位：匯出預設（套用／存成預設／刪除，都可以從 toast 復原）、格式＋位元深度、品質＋檔案上限、尺寸、中繼資料＋移除 GPS、
 * 輸出銳利化；底下一行摘要。哪些控制項停用只由 domain/export 的 `exportDialogState` 決定（例如 WebP 不能寫時停用並寫原因）。
 * 改了任何一項、跟選中的匯出預設不一樣了，選單就回到「（自訂）」。
 * 匯出本身在 hooks/useExportStore（開著的這張送畫面上的參數；選取的只送路徑）；永遠不送資料夾。
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Select,
  TextField,
} from '@mui/material';
import {
  EXPORT_FORMATS,
  EXPORT_SETTINGS_KEY,
  FORMAT_LABELS,
  METADATA_MODES,
  RESIZE_MODES,
  SHARPEN_AMOUNTS,
  SHARPEN_TARGETS,
  defaultBitDepth,
  exportDialogState,
  exportFormFromSettings,
  exportPresetDeleted,
  exportPresetSaved,
  exportPresetUpdated,
  exportSettingsFrom,
  exportSummary,
  resizeTarget,
  sameSettings,
  settingsFromForm,
  type ExportForm,
  type ExportSettings,
} from '../../domain/export';
import { explain } from '../../domain/errors';
import { gridCount } from '../../domain/library';
import { baseName } from '../../domain/text';
import { fitCrop } from '../../domain/geometry';
import * as exportReq from '../../requests/exports';
import { keys, queryClient, useCapabilities, useExportPresets } from '../../hooks/queries';
import { ask, confirmAsk, toast, toastAction } from '../../hooks/useAppStore';
import { useEditStore } from '../../hooks/useEditStore';
import { useExportStore } from '../../hooks/useExportStore';
import { useLibraryStore } from '../../hooks/useLibraryStore';
import { useT } from '../../hooks/useT';
import { loadRaw } from '../../utils/storage';
import css from './ExportDialog.module.scss';

export function ExportDialog() {
  const t = useT();
  const open = useExportStore((s) => s.open);
  const target = useExportStore((s) => s.target);
  const busy = useExportStore((s) => s.busy);
  const image = useLibraryStore((s) => s.image);
  const selCount = useLibraryStore((s) => s.grid.sel.size);
  const total = useLibraryStore((s) => s.grid.items.length);
  const geometry = useEditStore((s) => s.ed.geometry);
  const { data: caps } = useCapabilities();
  const { data: presets = [] } = useExportPresets(open);
  const [form, setForm] = useState<Required<ExportForm>>(() => exportFormFromSettings(exportSettingsFrom(null)));
  const [chosen, setChosen] = useState('');

  // 每次打開：填上次用的設定（localStorage）
  useEffect(() => {
    if (!open) return;
    setForm(exportFormFromSettings(exportSettingsFrom(loadRaw('local', EXPORT_SETTINGS_KEY))));
    setChosen('');
    void queryClient.invalidateQueries({ queryKey: keys.exportPresets });
  }, [open]);

  const settings = useMemo(() => settingsFromForm(form), [form]);
  const ds = exportDialogState(settings, caps ?? null);
  const preset = presets.find((p) => p.name === chosen);
  // 手動改過、跟選中的預設不一樣：回到（自訂）
  const shownChoice = preset && sameSettings(preset.settings, settings) ? chosen : '';

  const set = (patch: Partial<ExportForm>) => setForm((f) => ({ ...f, ...patch }));
  const fill = (s: ExportSettings) => setForm((f) => exportFormFromSettings(s, f));

  const refresh = async (select: string) => {
    await queryClient.invalidateQueries({ queryKey: keys.exportPresets });
    setChosen(select);
  };

  const saveAsPreset = async () => {
    const name = await ask({ title: t('export.presetNamePrompt'), initial: shownChoice, confirmLabel: t('export.saveAs').replace('…', '') });
    if (name === null) return;
    let res: Awaited<ReturnType<typeof exportReq.saveExportPreset>>;
    try {
      res = await exportReq.saveExportPreset(name, settings);
    } catch (e) {
      toast(explain((e as Error).message, t), true, (e as Error).message);
      return;
    }
    fill(exportSettingsFrom(res.settings));
    await refresh(res.name);
    const prev = res.previous;
    if (prev) {
      toastAction(exportPresetUpdated(res.name, t), t('common.undo'), async () => {
        try {
          await exportReq.saveExportPreset(res.name, prev);
        } catch (e) {
          toast(explain((e as Error).message, t), true, (e as Error).message);
        }
        await refresh(res.name);
      });
    } else {
      toastAction(exportPresetSaved(res.name, t), t('common.undo'), async () => {
        try {
          await exportReq.deleteExportPreset(res.name);
        } catch (e) {
          toast(explain((e as Error).message, t), true, (e as Error).message);
        }
        await refresh('');
      });
    }
  };

  const deletePreset = async () => {
    if (!shownChoice) return;
    if (!(await confirmAsk({ title: t('export.presetDeleteConfirm', { name: shownChoice }), confirmLabel: t('export.presetDeleteGo', { name: shownChoice }), danger: true })))
      return;
    let res: Awaited<ReturnType<typeof exportReq.deleteExportPreset>>;
    try {
      res = await exportReq.deleteExportPreset(shownChoice);
    } catch (e) {
      toast(explain((e as Error).message, t), true, (e as Error).message);
      return;
    }
    await refresh('');
    toastAction(exportPresetDeleted(res.name, t), t('common.undo'), async () => {
      try {
        await exportReq.saveExportPreset(res.name, res.settings);
      } catch (e) {
        toast(explain((e as Error).message, t), true, (e as Error).message);
      }
      await refresh(res.name);
    });
  };

  const go = () => {
    if (busy || ds.go.disabled) return;
    void useExportStore.getState().run(settings);
  };

  // 開著的這張：依目前裁切與縮放算輸出尺寸（伺服器的 E8 規則鏡像）
  let outSize: [number, number] | null = null;
  if (target === 'photo' && image) {
    const c = geometry ? fitCrop(geometry, image.width, image.height) : { width: image.width, height: image.height };
    const r = settings.resize;
    outSize = r && typeof r.value === 'number' ? resizeTarget(c.width, c.height, { mode: String(r.mode), value: r.value }) : [c.width, c.height];
  }

  const sub = target === 'photo' ? (image ? baseName(image.path) : '') : gridCount(selCount, total, t);

  return (
    <Dialog open={open} onClose={() => useExportStore.getState().closeDialog()} fullWidth aria-labelledby="xd-title">
      <form
        autoComplete="off"
        onSubmit={(e) => {
          e.preventDefault();
          go();
        }}
        onKeyDown={(e) => {
          const el = e.target as HTMLElement;
          // Enter 匯出（在按鈕、勾選框、選單上按 Enter 照它們自己的意思）
          if (e.key === 'Enter' && !el.matches('button, input[type=checkbox], [role=combobox], [role=option]')) {
            e.preventDefault();
            go();
          }
        }}
      >
        <DialogTitle id="xd-title" className={css.title}>
          {t('export.title')}
          <span className={css.sub}>{sub}</span>
        </DialogTitle>
        <DialogContent className={css.body}>
          <Row label={t('export.preset')} htmlFor="xd-preset">
            <Select
              id="xd-preset"
              value={shownChoice}
              displayEmpty
              title={t('export.presetTitle')}
              onChange={(e) => {
                const name = String(e.target.value);
                const p = presets.find((x) => x.name === name);
                if (p) fill(exportSettingsFrom(p.settings));
                setChosen(name);
              }}
            >
              <MenuItem value="">{t('export.custom')}</MenuItem>
              {presets.map((p) => (
                <MenuItem key={p.name} value={p.name}>
                  {p.name}
                </MenuItem>
              ))}
            </Select>
            <Button variant="text" title={t('export.saveAsTitle')} onClick={() => void saveAsPreset()}>
              {t('export.saveAs')}
            </Button>
            <Button variant="text" title={t('export.deleteTitle')} disabled={!shownChoice} onClick={() => void deletePreset()}>
              {t('export.delete')}
            </Button>
          </Row>
          <Row label={t('export.format')} htmlFor="xd-format">
            <Select
              id="xd-format"
              value={form.format}
              title={t('export.formatTitle')}
              onChange={(e) => {
                const f = String(e.target.value);
                set({ format: f, bit_depth: String(defaultBitDepth(f)) });
              }}
            >
              {EXPORT_FORMATS.map((f) => (
                <MenuItem key={f} value={f} disabled={f === 'webp' && ds.webp.disabled} title={f === 'webp' ? ds.webp.title : undefined}>
                  {FORMAT_LABELS[f]}
                </MenuItem>
              ))}
            </Select>
            <label className={css.subLabel} htmlFor="xd-bit-depth">
              {t('export.bitDepth')}
            </label>
            <Select
              id="xd-bit-depth"
              value={ds.bitDepth.disabled ? '8' : form.bit_depth}
              title={t('export.bitDepthTitle')}
              disabled={ds.bitDepth.disabled}
              onChange={(e) => set({ bit_depth: String(e.target.value) })}
            >
              {['8', '16'].map((b) => (
                <MenuItem key={b} value={b} disabled={!ds.bitDepth.options.includes(Number(b))}>
                  {b}-bit
                </MenuItem>
              ))}
            </Select>
          </Row>
          <Row label={t('export.quality')} htmlFor="xd-quality">
            <TextField
              id="xd-quality"
              type="number"
              className={css.num}
              value={form.quality}
              disabled={ds.quality.disabled}
              title={t('export.qualityTitle')}
              slotProps={{ htmlInput: { min: 1, max: 100, step: 1 } }}
              onChange={(e) => set({ quality: e.target.value })}
            />
            <FormControlLabel
              className={css.check}
              title={t('export.maxKbOnTitle')}
              disabled={ds.maxKbOn.disabled}
              control={<Checkbox checked={form.max_kb_on && !ds.maxKbOn.disabled} onChange={(e) => set({ max_kb_on: e.target.checked })} />}
              label={t('export.maxKbOn')}
            />
            <TextField
              type="number"
              className={css.num}
              value={form.max_kb}
              disabled={ds.maxKb.disabled}
              title={t('export.maxKbTitle')}
              slotProps={{ htmlInput: { min: 10, max: 1048576, step: 1, 'aria-label': t('export.maxKbTitle') } }}
              onChange={(e) => set({ max_kb: e.target.value })}
            />
            <span className={css.mute}>{t('export.kb')}</span>
          </Row>
          <Row label={t('export.resize')} htmlFor="xd-resize-mode">
            <Select
              id="xd-resize-mode"
              value={form.resize_mode}
              displayEmpty
              title={t('export.resizeTitle')}
              onChange={(e) => set({ resize_mode: String(e.target.value) })}
            >
              <MenuItem value="">{t('export.noResize')}</MenuItem>
              {RESIZE_MODES.map((m) => (
                <MenuItem key={m} value={m}>
                  {t(`export.resizeModes.${m}`)}
                </MenuItem>
              ))}
            </Select>
            <TextField
              type="number"
              className={css.num}
              value={form.resize_value}
              disabled={ds.resizeValue.disabled}
              title={t('export.resizeValueTitle')}
              slotProps={{
                htmlInput: { min: ds.resizeValue.min, max: ds.resizeValue.max, step: ds.resizeValue.step, 'aria-label': t('export.resizeValueTitle') },
              }}
              onChange={(e) => set({ resize_value: e.target.value })}
            />
            {outSize && <span className={css.mute}>{t('export.outputSize', { w: outSize[0], h: outSize[1] })}</span>}
          </Row>
          <Row label={t('export.metadata')} htmlFor="xd-metadata">
            <Select id="xd-metadata" value={form.metadata} title={t('export.metadataTitle')} onChange={(e) => set({ metadata: String(e.target.value) })}>
              {METADATA_MODES.map((m) => (
                <MenuItem key={m} value={m}>
                  {t(`export.metadataModes.${m}`)}
                </MenuItem>
              ))}
            </Select>
            <FormControlLabel
              className={css.check}
              title={t('export.removeGpsTitle')}
              disabled={ds.removeGps.disabled}
              control={<Checkbox checked={form.remove_gps} onChange={(e) => set({ remove_gps: e.target.checked })} />}
              label={t('export.removeGps')}
            />
          </Row>
          <Row label={t('export.sharpen')} htmlFor="xd-sharpen-target">
            <Select
              id="xd-sharpen-target"
              value={form.sharpen_target}
              displayEmpty
              title={t('export.sharpenTitle')}
              onChange={(e) => set({ sharpen_target: String(e.target.value) })}
            >
              <MenuItem value="">{t('export.noSharpen')}</MenuItem>
              {SHARPEN_TARGETS.map((m) => (
                <MenuItem key={m} value={m}>
                  {t(`export.sharpenTargets.${m}`)}
                </MenuItem>
              ))}
            </Select>
            <Select
              value={form.sharpen_amount}
              disabled={ds.sharpenAmount.disabled}
              title={t('export.sharpenAmountTitle')}
              inputProps={{ 'aria-label': t('export.sharpenAmountTitle') }}
              onChange={(e) => set({ sharpen_amount: String(e.target.value) })}
            >
              {SHARPEN_AMOUNTS.map((m) => (
                <MenuItem key={m} value={m}>
                  {t(`export.sharpenAmounts.${m}`)}
                </MenuItem>
              ))}
            </Select>
          </Row>
          <div className={css.summary} role="status">
            {exportSummary(settings, t)}
          </div>
        </DialogContent>
        <DialogActions>
          <Button title={t('export.cancelTitle')} onClick={() => useExportStore.getState().closeDialog()}>
            {t('common.cancel')}
          </Button>
          <Button
            type="submit"
            variant="contained"
            autoFocus
            disabled={busy || ds.go.disabled}
            title={ds.go.disabled ? ds.webp.title : t('export.goTitle')}
          >
            {busy ? t('export.busy') : t('export.go')}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

function Row({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className={css.row}>
      <label htmlFor={htmlFor} className={css.label}>
        {label}
      </label>
      <span className={css.ctl}>{children}</span>
    </div>
  );
}
