/**
 * 右欄：滑桿分區（基本、曲線、HSL、顏色分級、細節、效果、校正），每區是一個平的 Accordion。
 *
 * 從舊 app.js 的 renderSliders／sliderRow／curveBox 搬來（R3 語意、R6 直接輸入、S17 滑桿繪製、DESIGN.md §6.1）：
 *   - 列的版面：標籤 84px｜滑桿｜數值 96px｜↺ 18px；HSL 列的標籤前有 6px 色相點。
 *   - 滑桿的畫面值＝clamp(preset×強度)＋微調；琥珀段＝你的微調、灰刻度＝preset 落點；被夾住時方形把手＋「（原 …）」。
 *   - 拖一次＝一步復原；雙擊滑桿或標籤＝還原這一項；點兩下數值可以直接輸入（Enter 確認、Esc 取消）。
 *   - 分區標題右邊：有微調時琥珀點＋「微調 N 項」。展開狀態記在 localStorage（darkroom.openGroups）。
 *   - 曲線區：preset 的點曲線（唯讀，依強度縮放），由 domain/edit 的 curveAtStrength／curvePath 畫。
 * 資料：滑桿表（TanStack Query）、編輯狀態與 preset 細節（useEditStore）。
 */
import { memo, useState, type CSSProperties } from 'react';
import { Accordion, AccordionDetails, AccordionSummary, Slider, Tab, Tabs, TextField } from '@mui/material';
import clsx from 'clsx';
import {
  CURVE_CHANNELS,
  bipolar,
  clampNote,
  curveAtStrength,
  curvePath,
  fmtNum,
  hueDot,
  parseValueInput,
  sliderTooltip,
  sliderValueText,
  sliderVars,
  sliderView,
  strengthInEffect,
  type Slider as SliderSpec,
} from '../../domain/edit';
import { useSliders } from '../../hooks/queries';
import { useEditStore } from '../../hooks/useEditStore';
import { useT } from '../../hooks/useT';
import { loadPref, savePref } from '../../utils/storage';
import { Icon } from '../common/Icon';
import css from './SliderPanel.module.scss';

export function SliderPanel() {
  const t = useT();
  const { data } = useSliders();
  const tweaks = useEditStore((s) => s.ed.tweaks);
  const [open, setOpen] = useState<Record<string, boolean>>(() => loadPref('openGroups', { basic: true }));
  const [hslTab, setHslTab] = useState<'h' | 's' | 'l'>('h');
  if (!data) return <section className={css.col} aria-label={t('editor.slidersLabel')} />;

  return (
    <section className={css.col} aria-label={t('editor.slidersLabel')}>
      {data.groups.map(([g, gname]) => {
        const all = data.sliders.filter((s) => s.group === g);
        const n = all.filter((s) => tweaks[s.key]).length;
        const list = g === 'hsl' ? all.filter((s) => s.sub === hslTab) : all;
        return (
          <Accordion
            key={g}
            expanded={!!open[g]}
            onChange={(_, ex) => {
              const next = { ...open, [g]: ex };
              setOpen(next);
              savePref('openGroups', next);
            }}
            slotProps={{ transition: { timeout: 0, unmountOnExit: true } }}
          >
            <AccordionSummary expandIcon={<Icon name="chevron" size={12} />}>
              <span className={css.gname}>{t(`sliderGroups.${g}`, { defaultValue: gname })}</span>
              {n > 0 && (
                <span className={css.tc}>
                  <i className={css.tdot} aria-hidden="true" />
                  {t('editor.tweakCount', { n })}
                </span>
              )}
            </AccordionSummary>
            <AccordionDetails>
              {g === 'hsl' && (
                <Tabs className="dr-segmented" value={hslTab} onChange={(_, v) => setHslTab(v)}>
                  {(['h', 's', 'l'] as const).map((k) => (
                    <Tab key={k} value={k} label={t(`editor.hsl.${k}`)} />
                  ))}
                </Tabs>
              )}
              {g === 'curve' && <CurveBox />}
              {list.map((s) => (
                <SliderRow key={s.key} spec={s} />
              ))}
            </AccordionDetails>
          </Accordion>
        );
      })}
    </section>
  );
}

/** 一列滑桿。只訂閱自己需要的狀態，拖一條時其他列不重畫。 */
const SliderRow = memo(function SliderRow({ spec: s }: { spec: SliderSpec }) {
  const t = useT();
  const tweak = useEditStore((st) => st.ed.tweaks[s.key] || 0);
  const strength = useEditStore((st) => strengthInEffect(st.ed));
  const presetValue = useEditStore((st) => (st.detail && st.detail.values[s.key] != null ? st.detail.values[s.key] : s.default));
  const [editing, setEditing] = useState<string | null>(null);
  const v = sliderView(s, presetValue, strength, tweak);
  const vars = sliderVars(s, v);
  const label = t(`sliders.${s.key}`, { defaultValue: s.label });
  const dot = hueDot(s.key);
  const es = useEditStore.getState;
  const reset = () => void es().dispatch({ type: 'resetKey', key: s.key });
  const commit = (text: string) => {
    const val = parseValueInput(text, s);
    setEditing(null);
    if (val !== null) void es().setValue(s.key, val);
  };

  return (
    <div
      className={clsx(css.row, tweak && css.adjusted, v.clamped && css.clamped)}
      title={sliderTooltip(s, presetValue, strength, tweak, t)}
    >
      <label className={css.label} onDoubleClick={reset}>
        {dot && <span className={css.hue} style={{ background: dot }} />}
        <span className={css.labelText}>{label}</span>
      </label>
      <Slider
        className={clsx(
          css.slider,
          bipolar(s) && 'dr-bipolar',
          tweak && 'dr-adjusted',
          v.clamped && ['dr-clamped', v.clamped === 'max' ? 'dr-at-max' : 'dr-at-min'],
        )}
        style={{ '--dr-base': vars.base, '--dr-lo': vars.lo, '--dr-hi': vars.hi } as CSSProperties}
        min={s.min}
        max={s.max}
        step={s.step}
        value={v.value}
        aria-label={label}
        getAriaValueText={() => sliderValueText(s, v, label, t)}
        onChange={(_, val) => void es().setValue(s.key, val as number, 'slider:' + s.key)} // 一次拖曳＝一步
        onChangeCommitted={() => es().endGesture()}
        onDoubleClick={reset}
      />
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
          slotProps={{ htmlInput: { 'aria-label': label } }}
        />
      ) : (
        <span
          className={css.vals}
          title={t('editor.valueTitle')}
          onDoubleClick={() => setEditing(fmtNum(s, v.value).replace(/^\+/, ''))}
        >
          <span className={css.v}>{fmtNum(s, v.value)}</span>
          {v.clamped && <span className={css.cn}>{clampNote(v, t)}</span>}
        </span>
      )}
      <button type="button" className={css.reset} title={t('editor.resetKey')} aria-label={t('editor.resetKey')} onClick={reset}>
        ↺
      </button>
    </div>
  );
});

/** preset 的點曲線（唯讀，套用目前強度）。 */
function CurveBox() {
  const t = useT();
  const curves = useEditStore((s) => s.detail?.curves ?? {});
  const strength = useEditStore((s) => strengthInEffect(s.ed));
  const size = 200;
  const paths = CURVE_CHANNELS.filter(([k]) => curves[k]).map(([k, col]) => (
    <path
      key={k}
      d={curvePath(curveAtStrength(curves[k], strength), size)}
      fill="none"
      stroke={col}
      strokeWidth={2}
      strokeOpacity={k === CURVE_CHANNELS[0][0] ? 1 : 0.85}
    />
  ));
  return (
    <div className={css.curve}>
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={t('editor.curveAria')}>
        <g stroke="var(--dr-track)">
          <path d="M50 0V200M100 0V200M150 0V200M0 50H200M0 100H200M0 150H200" />
        </g>
        <path d={`M0 ${size}L${size} 0`} stroke="var(--dr-track-2)" strokeDasharray="3 3" />
        {paths}
      </svg>
      <div className={css.note}>{paths.length ? t('editor.curveNote', { strength }) : t('editor.curveNone')}</div>
    </div>
  );
}
