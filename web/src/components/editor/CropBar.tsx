/**
 * 裁切工具列（裁切模式才出現，role="toolbar"）：比例、直式／橫式、拉直（滑桿＋數字）、左右轉 90°、水平／垂直鏡像、
 * 重設、提示、取消、完成。照舊 index.html 的 #crop-panel（C22、C23）。
 *
 * 每個動作都只改裁切模式的草稿（useEditStore.crop），完成時才變成編輯的一步；取消就像什麼都沒發生。
 * 比例選單依草稿目前的方向顯示直式或橫式的比例；代理寫進來的奇怪比例原樣列出。
 */
import { useEffect, useState, type CSSProperties } from 'react';
import { MenuItem, Select, Slider, TextField } from '@mui/material';
import { ANGLE_STEP, aspectOptions, cropOrientation, fitCrop, fullGeometry } from '../../domain/geometry';
import { useEditStore } from '../../hooks/useEditStore';
import { useLibraryStore } from '../../hooks/useLibraryStore';
import { useT } from '../../hooks/useT';
import { ToolButton } from '../common/ToolButton';
import css from './CropBar.module.scss';

export function CropBar() {
  const t = useT();
  const crop = useEditStore((s) => s.crop);
  const image = useLibraryStore((s) => s.image);
  const draft = crop?.draft;
  const [angleText, setAngleText] = useState(String(draft?.angle ?? 0));
  const [angleFocus, setAngleFocus] = useState(false);
  useEffect(() => {
    if (!angleFocus) setAngleText(String(draft?.angle ?? 0));
  }, [draft?.angle, angleFocus]);
  if (!draft || !image) return null;
  const es = useEditStore.getState;
  const orient = cropOrientation(draft, image.width, image.height);
  const options = aspectOptions(orient === 'landscape', t);
  if (!options.some(([v]) => v === draft.aspect)) options.push([draft.aspect, draft.aspect]);
  const orientDisabled = draft.aspect === 'free' || draft.aspect === '1:1';

  // 拉直：0.1 度一格；最新的畫面預覽贏（B7），框自己縮進來
  const angle = (v: number, gesture?: string) => {
    if (!Number.isFinite(v)) return;
    const a = Math.round(Math.min(45, Math.max(-45, v)) / ANGLE_STEP) * ANGLE_STEP;
    es().cropChange({ ...fullGeometry(es().crop?.draft), angle: Math.round(a * 10) / 10 }, gesture);
  };

  return (
    <div className={css.bar} role="toolbar" aria-label={t('crop.toolbar')}>
      <label className={css.lbl} htmlFor="crop-aspect">
        {t('crop.aspect')}
      </label>
      <Select
        id="crop-aspect"
        value={draft.aspect}
        title={t('crop.aspectTitle')}
        onChange={(e) => {
          const d = { ...fullGeometry(es().crop?.draft), aspect: String(e.target.value) };
          if (d.crop) {
            const b = fitCrop(d, image.width, image.height).box;
            d.crop = { left: b[0], top: b[1], right: b[2], bottom: b[3] };
          }
          es().cropChange(d);
        }}
      >
        {options.map(([v, label]) => (
          <MenuItem key={v} value={v}>
            {label}
          </MenuItem>
        ))}
      </Select>
      <ToolButton
        label={orient === 'portrait' ? t('crop.landscape') : t('crop.portrait')}
        title={t('crop.orientTitle')}
        collapsible={false}
        disabled={orientDisabled}
        onClick={() => es().geometryAct('orient')}
      />
      <label className={css.lbl} htmlFor="crop-angle-num">
        {t('crop.angle')}
      </label>
      <Slider
        className={css.angle}
        min={-45}
        max={45}
        step={ANGLE_STEP}
        value={draft.angle}
        title={t('crop.angleTitle')}
        aria-label={t('crop.angle')}
        style={{ '--dr-base': '50%', '--dr-lo': '50%', '--dr-hi': '50%' } as CSSProperties}
        onChange={(_, v) => angle(v as number, 'angle')}
        onChangeCommitted={() => es().cropEndGesture()}
        onDoubleClick={() => angle(0)}
      />
      <TextField
        id="crop-angle-num"
        type="number"
        className={css.num}
        value={angleText}
        title={t('crop.angleNumTitle')}
        slotProps={{ htmlInput: { min: -45, max: 45, step: 0.1 } }}
        onFocus={() => setAngleFocus(true)}
        onBlur={() => {
          setAngleFocus(false);
          angle(parseFloat(angleText));
        }}
        onChange={(e) => setAngleText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            e.stopPropagation();
            angle(parseFloat(angleText));
          }
        }}
      />
      <ToolButton label={t('crop.rotateLeft')} title={t('crop.rotateLeftTitle')} collapsible={false} onClick={() => es().geometryAct('rotate_left')} />
      <ToolButton label={t('crop.rotateRight')} title={t('crop.rotateRightTitle')} collapsible={false} onClick={() => es().geometryAct('rotate_right')} />
      <ToolButton label={t('crop.flipH')} title={t('crop.flipH')} collapsible={false} onClick={() => es().geometryAct('flip_h')} />
      <ToolButton label={t('crop.flipV')} title={t('crop.flipV')} collapsible={false} onClick={() => es().geometryAct('flip_v')} />
      <ToolButton label={t('crop.reset')} title={t('crop.resetTitle')} collapsible={false} onClick={() => es().cropStep('reset')} />
      <span className={css.hint}>{t('crop.hint')}</span>
      <span className={css.sp} />
      <ToolButton label={t('crop.cancel')} title={t('crop.cancelTitle')} collapsible={false} onClick={() => void es().leaveCrop(false)} />
      <ToolButton
        label={t('crop.done')}
        title={t('crop.doneTitle')}
        collapsible={false}
        variant="contained"
        onClick={() => void es().leaveCrop(true)}
      />
    </div>
  );
}
