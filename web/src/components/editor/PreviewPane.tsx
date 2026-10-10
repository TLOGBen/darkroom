/**
 * 中間欄：預覽工具列（38px 一行）、裁切工具列（裁切模式才有）、照片（canvas 底）、強度轉盤。
 *
 * 照片永遠是後端算的（POST /api/preview），頁面從不假裝改顏色；圖換上時沒有過場（DESIGN.md §7）。
 * 疊在照片上的東西都依「照片實際畫出來的矩形」定位（ResizeObserver＋圖片載入時量）：
 *   - 按住看原圖（\ 或按住按鈕）：換成原圖預覽並標「原圖」；視窗失焦、分頁切走時自動放開（S13 d）。
 *   - A/B 對照（Y）：原圖疊在上面、從分隔線裁開；拖分隔線不問後端；分隔線位置記在 sessionStorage（S7）。
 *   - 裁切框（R）：整個轉正畫面上的框＋8 個把手；拖動不問後端，結果一定過 fitCrop（C3、C23）。
 * 資料：useEditStore（預覽、對照、裁切、目前 preset 細節）、useLibraryStore（照片、編輯狀態句子）。
 */
import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as RPointerEvent } from 'react';
import clsx from 'clsx';
import { AB_DEFAULT_SPLIT, CANVASES, abStep, canSavePreset } from '../../domain/edit';
import { cropKeyMove, fitCrop, type CropHandle, type Geometry } from '../../domain/geometry';
import { capReason } from '../../domain/settings';
import { useCapabilities } from '../../hooks/queries';
import { useEditStore } from '../../hooks/useEditStore';
import { useLibraryStore } from '../../hooks/useLibraryStore';
import { useExportStore } from '../../hooks/useExportStore';
import { usePresetStore } from '../../hooks/usePresetStore';
import { useLayoutStore } from '../../hooks/useLayoutStore';
import { useT } from '../../hooks/useT';
import { ToolButton } from '../common/ToolButton';
import { CropBar } from './CropBar';
import { StrengthDial } from './StrengthDial';
import css from './PreviewPane.module.scss';

const HANDLES: CropHandle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

interface Rect {
  l: number;
  t: number;
  w: number;
  h: number;
}

export function PreviewPane() {
  const t = useT();
  const { data: caps } = useCapabilities();
  const image = useLibraryStore((s) => s.image);
  const openError = useLibraryStore((s) => s.openError);
  const hasEdit = useLibraryStore((s) => !!s.edit);
  const previous = useLibraryStore((s) => s.previous);
  const editStatusText = useLibraryStore((s) => {
    void s.editStatus;
    void s.editUnreadable;
    return s.editStatusText();
  });
  const previewUrl = useEditStore((s) => s.previewUrl);
  const previewKind = useEditStore((s) => s.previewKind);
  const holding = useEditStore((s) => s.holding);
  const originalUrl = useEditStore((s) => s.originalUrl);
  // 原圖是不是目前這張、這個幾何的（照片、幾何、裁切草稿變了都會重算）；不是就繼續顯示預覽，等新的原圖算好
  const originalFresh = useEditStore((s) => {
    void s.originalFor;
    void s.ed;
    void s.crop;
    return s.originalIsCurrent();
  });
  const ab = useEditStore((s) => s.ab);
  const crop = useEditStore((s) => s.crop);
  const detail = useEditStore((s) => s.detail);
  const skipOpen = useEditStore((s) => s.skipOpen);
  const ed = useEditStore((s) => s.ed);
  const exportBusy = useExportStore((s) => s.busy);
  const canvas = useLayoutStore((s) => s.canvas);

  const wrapRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const [abDragging, setAbDragging] = useState(false);
  const drag = useRef<null | { handle: CropHandle; x: number; y: number; start: Geometry; w: number; h: number }>(null);
  const [boxDragging, setBoxDragging] = useState(false);

  const cropOn = !!crop?.active;
  const showingOriginal = holding && !!originalUrl && originalFresh;
  const shownUrl = showingOriginal ? originalUrl : previewUrl;
  const photoLibOff = capReason(caps ?? null, 'photo_library');
  const writesOff = capReason(caps ?? null, 'preset_library_writes');

  // 照片實際畫出來的矩形（object-fit 之後）：疊層都用它定位
  const measure = () => {
    const img = imgRef.current;
    if (!img || !img.naturalWidth) return setRect(null);
    setRect({ l: img.offsetLeft, t: img.offsetTop, w: img.offsetWidth, h: img.offsetHeight });
  };
  useLayoutEffect(measure, [shownUrl]);
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap || typeof ResizeObserver !== 'function') return;
    const ro = new ResizeObserver(measure);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, []);

  // S13 (d)：視窗失焦就收不到 keyup，原圖不能一直卡在畫面上
  useEffect(() => {
    const release = () => {
      if (useEditStore.getState().holding) void useEditStore.getState().showOriginal(false);
    };
    const vis = () => document.hidden && release();
    window.addEventListener('blur', release);
    document.addEventListener('visibilitychange', vis);
    return () => {
      window.removeEventListener('blur', release);
      document.removeEventListener('visibilitychange', vis);
    };
  }, []);

  const es = useEditStore.getState;
  const lib = useLibraryStore.getState;

  // ---- A/B 分隔線 ----
  const abMoveTo = (clientX: number) => {
    const r = imgRef.current?.getBoundingClientRect();
    if (r && r.width) es().abSetSplit((clientX - r.left) / r.width);
  };
  const onAbDown = (e: RPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setAbDragging(true);
    abMoveTo(e.clientX);
  };

  // ---- 裁切框 ----
  const box = cropOn && rect && image && previewKind === 'frame' ? fitCrop(crop?.draft, image.width, image.height).box : null;
  const onBoxDown = (e: RPointerEvent<HTMLDivElement>) => {
    if (!cropOn || !rect) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const h = (e.target as HTMLElement).dataset.h as CropHandle | undefined;
    drag.current = { handle: h ?? 'move', x: e.clientX, y: e.clientY, start: crop?.draft as Geometry, w: rect.w, h: rect.h };
    setBoxDragging(true);
  };
  const onBoxMove = (e: RPointerEvent<HTMLDivElement>) => {
    const g = drag.current;
    if (!g) return;
    es().cropDragTo(g.start, g.handle, (e.clientX - g.x) / g.w, (e.clientY - g.y) / g.h, g.w, g.h, 'drag');
  };
  const onBoxUp = () => {
    if (!drag.current) return;
    drag.current = null;
    setBoxDragging(false);
    es().cropEndGesture();
  };

  const skipBanner = detail?.banner ?? '';
  const skipNote = detail?.note ?? '';

  return (
    <section className={css.col} aria-label={t('editor.previewAlt')}>
      <div className={css.tools}>
        <span className={css.seg}>
          <ToolButton
            label={t('editor.hold')}
            title={t('editor.holdTitle')}
            collapsible={false}
            pressed={holding}
            disabled={!image}
            onPointerDown={() => void es().showOriginal(true)}
            onPointerUp={() => holding && void es().showOriginal(false)}
            onPointerLeave={() => holding && void es().showOriginal(false)}
          />
          <ToolButton
            label={t('editor.compare')}
            title={cropOn ? t('crop.abDisabled') : t('editor.compareTitle')}
            collapsible={false}
            pressed={ab.on}
            disabled={!image || cropOn}
            onClick={() => void es().abToggle()}
          />
        </span>
        <ToolButton
          label={t('editor.crop')}
          title={t('editor.cropTitle')}
          collapsible={false}
          pressed={cropOn}
          disabled={!image}
          onClick={() => (cropOn ? void es().leaveCrop(true) : es().enterCrop())}
        />
        {skipBanner && (
          <span
            className={css.warnbar}
            role="button"
            tabIndex={0}
            title={skipBanner}
            onClick={() => es().setSkipOpen(!skipOpen)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                es().setSkipOpen(!skipOpen);
              }
            }}
          >
            {skipBanner}
          </span>
        )}
        {skipNote && (
          <span
            className={css.skipnote}
            role="button"
            tabIndex={0}
            title={skipNote}
            onClick={() => es().setSkipOpen(!skipOpen)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                es().setSkipOpen(!skipOpen);
              }
            }}
          >
            {skipNote}
          </span>
        )}
        {editStatusText && (
          <span className={css.editstatus} title={editStatusText}>
            {editStatusText}
          </span>
        )}
        <ToolButton
          label={t('editor.restorePrevious')}
          title={photoLibOff ?? t('editor.restorePreviousTitle')}
          collapsible={false}
          disabled={!(image && !hasEdit && previous) || photoLibOff !== null}
          onClick={() => void lib().restorePrevious()}
        />
        <span className={css.sp} />
        {image && (
          <span className={css.size} title={t('editor.photoSizeTitle', { w: image.preview_width, h: image.preview_height })}>
            {image.width}×{image.height}
          </span>
        )}
        <ToolButton
          label={t('editor.savePreset')}
          title={writesOff ?? t('editor.savePresetTitle')}
          collapsible={false}
          disabled={!canSavePreset(ed) || writesOff !== null}
          onClick={() => void usePresetStore.getState().savePreset()}
        />
        <ToolButton
          label={exportBusy ? t('export.busy') : t('editor.export')}
          title={t('editor.exportTitle')}
          collapsible={false}
          aria-haspopup="dialog"
          disabled={!image || exportBusy}
          onClick={() => void useExportStore.getState().openDialog('photo')}
        />
      </div>
      {cropOn && <CropBar />}
      <div
        ref={wrapRef}
        className={clsx(css.wrap, ab.on && css.ab, abDragging && css.dragging)}
        data-canvas={canvas}
      >
        {shownUrl && image ? (
          <img
            ref={imgRef}
            className={css.img}
            src={shownUrl}
            alt={t('editor.previewAlt')}
            draggable={false}
            onLoad={measure}
          />
        ) : (
          <div className={css.empty} title={openError?.original}>
            {openError ? openError.text : t('editor.empty')}
          </div>
        )}
        {showingOriginal && <span className={css.label}>{t('editor.original')}</span>}

        {ab.on && rect && originalUrl && originalFresh && !holding && (
          <>
            <img
              className={css.abOrig}
              src={originalUrl}
              alt=""
              aria-hidden="true"
              style={{
                left: rect.l,
                top: rect.t,
                width: rect.w,
                height: rect.h,
                clipPath: `inset(0 calc(100% - ${(ab.split * 100).toFixed(3)}%) 0 0)`,
              }}
            />
            <div
              className={css.abDivider}
              style={{ left: rect.l + ab.split * rect.w, top: rect.t, height: rect.h }}
              onPointerDown={onAbDown}
              onPointerMove={(e) => abDragging && abMoveTo(e.clientX)}
              onPointerUp={() => setAbDragging(false)}
              onDoubleClick={() => es().abSetSplit(AB_DEFAULT_SPLIT)}
            >
              <div
                className={css.abHandle}
                tabIndex={0}
                role="slider"
                aria-label={t('editor.abHandle')}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(ab.split * 100)}
                onKeyDown={(e) => {
                  const v = abStep(ab.split, e.key, e.shiftKey);
                  if (v === null) return;
                  e.preventDefault();
                  e.stopPropagation();
                  es().abSetSplit(v);
                }}
              >
                <i />
                <i />
              </div>
            </div>
            <span className={css.abTag} style={{ left: rect.l + 10, top: rect.t + 10 }}>
              {t('editor.original')}
            </span>
            <span
              className={css.abTag}
              style={{ right: (wrapRef.current?.clientWidth ?? 0) - rect.l - rect.w + 10, top: rect.t + 10 }}
            >
              {t('editor.edited')}
            </span>
          </>
        )}

        {box && rect && (
          <div
            className={clsx(css.cropBox, boxDragging && css.boxDragging)}
            tabIndex={0}
            role="group"
            aria-label={t('crop.box')}
            style={{
              left: rect.l + box[0] * rect.w,
              top: rect.t + box[1] * rect.h,
              width: (box[2] - box[0]) * rect.w,
              height: (box[3] - box[1]) * rect.h,
            }}
            onPointerDown={onBoxDown}
            onPointerMove={onBoxMove}
            onPointerUp={onBoxUp}
            onPointerCancel={onBoxUp}
            onKeyDown={(e) => {
              const mv = cropKeyMove(e.key, e.shiftKey);
              if (!mv || !cropOn) return;
              e.preventDefault();
              e.stopPropagation();
              es().cropDragTo(crop?.draft as Geometry, 'move', mv[0], mv[1], rect.w, rect.h, null);
            }}
          >
            <b className={css.thirds} />
            {HANDLES.map((h) => (
              <i key={h} data-h={h} className={css.handle} />
            ))}
          </div>
        )}

        {skipOpen && (skipBanner || skipNote) && (
          <div className={css.skipDetail} role="dialog" aria-label={t('editor.skipDetail')} onClick={() => es().setSkipOpen(false)}>
            {skipBanner && <p>{skipBanner}</p>}
            {skipNote && <p className={css.skipNoteFull}>{skipNote}</p>}
          </div>
        )}

        <div className={css.canvasPick} role="group" aria-label={t('editor.canvasGroup')}>
          {CANVASES.map((c) => (
            <button
              key={c}
              type="button"
              className={css[`c_${c}`]}
              title={t(`editor.canvas.${c}`)}
              aria-label={t(`editor.canvas.${c}`)}
              aria-pressed={canvas === c}
              onClick={() => useLayoutStore.getState().setCanvas(c)}
            />
          ))}
        </div>
      </div>
      <StrengthDial />
    </section>
  );
}
