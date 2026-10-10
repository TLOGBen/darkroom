/**
 * 左欄：preset 庫。上面是搜尋框＋匯入＋新群組，下面是匯入／下載的結果面板、數量、preset 樹。
 *
 * 資料：preset 列表、旗標、群組樹來自 hooks/queries（TanStack Query）；搜尋字與展開狀態在 usePresetStore。
 * 能力偵測說「整理 preset 庫」關閉時（例如 preset 庫落在照片資料夾裡），匯入與新群組停用、提示寫原因（E20、E23）。
 */
import { useRef } from 'react';
import { TextField } from '@mui/material';
import { capReason } from '../../domain/settings';
import { useCapabilities, usePresets } from '../../hooks/queries';
import { usePresetStore } from '../../hooks/usePresetStore';
import { useT } from '../../hooks/useT';
import { ResultPanel } from '../common/ResultPanel';
import { ToolButton } from '../common/ToolButton';
import { PresetTree } from './PresetTree';
import css from './PresetLibrary.module.scss';

export function PresetLibrary() {
  const t = useT();
  const { data: presets } = usePresets();
  const { data: caps } = useCapabilities();
  const search = usePresetStore((s) => s.search);
  const result = usePresetStore((s) => s.result);
  const fileRef = useRef<HTMLInputElement>(null);
  const writesOff = capReason(caps ?? null, 'preset_library_writes');

  return (
    <section className={css.col} aria-label={t('presets.libraryTitle')}>
      <div className={css.bar}>
        <TextField
          type="search"
          value={search}
          placeholder={t('presets.searchPlaceholder')}
          onChange={(e) => usePresetStore.getState().setSearch(e.target.value)}
          className={css.search}
          slotProps={{ htmlInput: { 'aria-label': t('presets.searchLabel'), spellCheck: false } }}
        />
        <ToolButton
          label={t('presets.import')}
          title={writesOff ?? t('presets.importTitle')}
          disabled={writesOff !== null}
          collapsible={false}
          onClick={() => fileRef.current?.click()}
        />
        <ToolButton
          label="＋"
          aria-label={t('presets.newGroup')}
          title={writesOff ?? t('presets.newGroup')}
          disabled={writesOff !== null}
          collapsible={false}
          sx={{ width: 26, px: 0 }}
          onClick={() => void usePresetStore.getState().newGroup('')}
        />
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".xmp"
          hidden
          onChange={(e) => {
            const files = [...(e.target.files ?? [])];
            e.target.value = '';
            void usePresetStore.getState().importFiles(files);
          }}
        />
      </div>
      {result && <ResultPanel summary={result.summary} lines={result.lines} onClose={() => usePresetStore.getState().setResult(null)} />}
      <div className={css.count}>{presets ? t('presets.count', { n: presets.length }) : t('presets.libraryTitle')}</div>
      <PresetTree />
    </section>
  );
}
