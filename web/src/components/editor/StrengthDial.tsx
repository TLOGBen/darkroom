/**
 * 預覽下方：「目前 preset：名稱」與強度轉盤（0～200%，DESIGN.md §6.1 強度轉盤）。
 *
 * - 沒有 preset 時強度停用、讀數顯示「—」（R5：強度只對 preset 有意義，沒有 preset 時微調以 100% 套用）。
 * - 拖一次＝一步復原（gesture 'strength'，放手時 endGesture）；讀數點兩下直接輸入（Enter 確認、Esc 取消）；
 *   「↺ 100%」一鍵回到 100%。
 * - 軌道畫法：左半 track、右半 track-2（>100% 是「誇張區」），100%→目前值那段用 text-2（不是琥珀：強度不是微調），
 *   由 domain/edit 的 strengthVars 算 CSS 變數。
 */
import { useState, type CSSProperties } from 'react';
import { Button, Slider, TextField, Typography } from '@mui/material';
import clsx from 'clsx';
import { parseValueInput, strengthEnabled, strengthVars } from '../../domain/edit';
import { presetsById } from '../../hooks/queries';
import { usePresets } from '../../hooks/queries';
import { useEditStore } from '../../hooks/useEditStore';
import { useT } from '../../hooks/useT';
import css from './StrengthDial.module.scss';

const STRENGTH = { min: 0, max: 200 };

export function StrengthDial() {
  const t = useT();
  usePresets(); // 名稱跟著 preset 庫更新
  const ed = useEditStore((s) => s.ed);
  const detail = useEditStore((s) => s.detail);
  const [editing, setEditing] = useState<string | null>(null);
  const on = strengthEnabled(ed);
  const vars = strengthVars(on ? ed.strength : 100);
  const es = useEditStore.getState;
  const byId = presetsById();
  const name = ed.presetId === null ? t('editor.noPreset') : (byId[ed.presetId]?.name ?? detail?.name ?? ed.presetId);

  const commit = (text: string) => {
    const v = parseValueInput(text, STRENGTH);
    setEditing(null);
    if (v !== null) void es().setStrength(v);
  };

  return (
    <div className={css.box}>
      <div className={css.row}>
        <span className={css.mute}>{t('editor.currentPreset')}</span>
        <span className={css.pname} title={name}>
          {name}
        </span>
      </div>
      <div className={css.row}>
        <label className={css.lbl} htmlFor="strength">
          {t('editor.strength')}
        </label>
        <div className={css.track} title={on ? undefined : t('editor.strengthNeedsPreset')}>
          <Slider
            id="strength"
            className={clsx('dr-strength', css.slider)}
            min={0}
            max={200}
            step={1}
            value={ed.strength}
            disabled={!on}
            marks={[
              { value: 0, label: '0' },
              { value: 100, label: '100' },
              { value: 200, label: '200' },
            ]}
            aria-label={t('editor.strength')}
            getAriaValueText={(v) => `${v}%`}
            style={{ '--dr-base': vars.base, '--dr-lo': vars.lo, '--dr-hi': vars.hi } as CSSProperties}
            onChange={(_, v) => void es().setStrength(v as number, 'strength')}
            onChangeCommitted={() => es().endGesture()}
          />
        </div>
        {editing !== null ? (
          <TextField
            autoFocus
            className={css.edit}
            value={editing}
            onChange={(e) => setEditing(e.target.value)}
            onFocus={(e) => e.target.select()}
            onBlur={() => commit(editing)}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === 'Enter') commit(editing);
              else if (e.key === 'Escape') setEditing(null);
            }}
            slotProps={{ htmlInput: { 'aria-label': t('editor.strength') } }}
          />
        ) : (
          <span
            className={css.readout}
            title={t('editor.strengthValueTitle')}
            onDoubleClick={() => on && setEditing(String(ed.strength))}
          >
            {on ? (
              <>
                <Typography variant="readout">{ed.strength}</Typography>
                <span className={css.pct}>%</span>
              </>
            ) : (
              <Typography variant="readout">—</Typography>
            )}
          </span>
        )}
        <Button title={t('editor.strength100Title')} disabled={!on} onClick={() => void es().setStrength(100)}>
          {t('editor.strength100')}
        </Button>
      </div>
    </div>
  );
}
