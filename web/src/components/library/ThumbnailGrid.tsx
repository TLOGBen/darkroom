/**
 * 縮圖格（第二個畫面，取代編輯器的三欄、頂列不變）：資料夾路徑＋載入、篩選（全部／已編輯／未編輯）、已選幾張、
 * 複製／貼上編輯（可勾「連同裁切與旋轉」）、還原成原圖、取回上一份、匯出所選；下面是結果面板與縮圖。
 *
 * 行為照舊 app.js（PL15／PLP9、S8 角標、S9 篩選與選取、S10 還原／取回、S13 縮圖記憶體與錯誤）：
 *   - 點一下＝只選這張；Ctrl＝加減；Shift＝範圍（篩選中只選得到看得到的）；點兩下或 Enter＝開到編輯器；空白＝加減。
 *   - 縮圖看得到才讀（IntersectionObserver，前後多 200px）；bytes 解碼後立刻釋放 object URL（S13 e）。
 *   - 有編輯：右下琥珀實心點；preset 已改或不見：空心圈；提示寫哪個 preset、多強（S8）。
 *   - 照片庫關閉時，編輯相關的按鈕停用、提示寫原因（E23）。
 * 資料：useLibraryStore（資料夾、項目、選取、剪貼簿）；縮圖位元組直接走 requests/library.thumbnail。
 */
import { memo, useEffect, useRef, useState } from 'react';
import { Checkbox, FormControlLabel, TextField } from '@mui/material';
import clsx from 'clsx';
import { FILTERS, badgeTitle, gridCount, gridFilter, gridPending, stale, type BadgeInfo } from '../../domain/library';
import { explain } from '../../domain/errors';
import { capReason } from '../../domain/settings';
import { thumbnail } from '../../requests/library';
import { useCapabilities } from '../../hooks/queries';
import { useLibraryStore } from '../../hooks/useLibraryStore';
import { useExportStore } from '../../hooks/useExportStore';
import { useT } from '../../hooks/useT';
import { ResultPanel } from '../common/ResultPanel';
import { ToolButton } from '../common/ToolButton';
import css from './ThumbnailGrid.module.scss';

export function ThumbnailGrid() {
  const t = useT();
  const { data: caps } = useCapabilities();
  const grid = useLibraryStore((s) => s.grid);
  const hasEdit = useLibraryStore((s) => !!s.edit);
  const clipboard = useLibraryStore((s) => s.clipboard);
  const pasteGeometry = useLibraryStore((s) => s.pasteGeometry);
  const result = useLibraryStore((s) => s.gridResult);
  const exportBusy = useExportStore((s) => s.busy);
  const [path, setPath] = useState(grid.folder ?? '');
  useEffect(() => {
    if (grid.folder) setPath(grid.folder);
  }, [grid.folder]);
  const lib = useLibraryStore.getState;
  const { shown, pending } = gridFilter(grid.items, grid.filter);
  const n = grid.sel.size;
  const off = capReason(caps ?? null, 'photo_library');
  const cellsRef = useRef<HTMLDivElement>(null);

  // 方向鍵在格子間移動焦點（S13 c：輸入框裡的方向鍵不管）
  const move = (from: HTMLElement, dir: 1 | -1) => {
    const cells = [...(cellsRef.current?.querySelectorAll<HTMLElement>('[data-cell]') ?? [])];
    const i = cells.indexOf(from);
    cells[i + dir]?.focus();
  };

  return (
    <main className={css.grid} data-grid>
      <div className={css.bar}>
        <form
          className={css.pathForm}
          onSubmit={(e) => {
            e.preventDefault();
            void lib().loadGrid(path);
          }}
        >
          <TextField
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder={t('grid.pathPlaceholder')}
            className={css.path}
            slotProps={{ htmlInput: { 'aria-label': t('grid.pathLabel'), spellCheck: false, className: 'dr-mono' } }}
          />
          <ToolButton type="submit" label={t('grid.load')} title={t('grid.loadTitle')} collapsible={false} />
        </form>
        <span className={css.seg} role="group" aria-label={t('grid.filterLabel')}>
          {FILTERS.map((f) => (
            <ToolButton
              key={f}
              label={t(`grid.filter.${f}`)}
              title={t(`grid.filterTitle.${f}`)}
              collapsible={false}
              pressed={grid.filter === f}
              onClick={() => void lib().setGridFilter(f)}
            />
          ))}
        </span>
        <span className={css.count}>{gridCount(n, shown.length, t)}</span>
        {pending > 0 && <span className={css.count}>{gridPending(pending, t)}</span>}
        <span className={css.sp} />
        <ToolButton label={t('grid.copyEdit')} title={off ?? t('grid.copyEditTitle')} collapsible={false} disabled={!hasEdit || off !== null} onClick={() => lib().copyEdit()} />
        <ToolButton
          label={t('grid.pasteEdit')}
          title={off ?? t('grid.pasteEditTitle')}
          collapsible={false}
          disabled={!(clipboard && n > 0) || off !== null}
          onClick={() => void lib().pasteEdit()}
        />
        <FormControlLabel
          className={css.check}
          title={t('grid.pasteGeometryTitle')}
          control={<Checkbox checked={pasteGeometry} onChange={(e) => lib().setPasteGeometry(e.target.checked)} />}
          label={t('grid.pasteGeometry')}
        />
        <ToolButton
          label={t('grid.resetOriginal')}
          title={off ?? t('grid.resetOriginalTitle')}
          collapsible={false}
          disabled={n === 0 || off !== null}
          onClick={() => void lib().gridResetOriginal()}
        />
        <ToolButton label={t('grid.restore')} title={off ?? t('grid.restoreTitle')} collapsible={false} disabled={n === 0 || off !== null} onClick={() => void lib().gridRestore()} />
        <ToolButton
          label={exportBusy ? t('export.busy') : t('grid.exportSelected')}
          title={off ?? t('grid.exportSelectedTitle')}
          collapsible={false}
          aria-haspopup="dialog"
          disabled={n === 0 || off !== null || exportBusy}
          onClick={() => void useExportStore.getState().openDialog('selected')}
        />
      </div>
      {result && (
        <ResultPanel summary={result.summary} lines={result.lines.map((l) => ({ ok: false, text: l }))} onClose={() => lib().setGridResult(null)} />
      )}
      <div className={css.cells} ref={cellsRef} role="listbox" aria-multiselectable="true" aria-label={t('grid.cellsLabel')}>
        {grid.folder !== null && !grid.items.length && <div className={css.empty}>{t('grid.empty')}</div>}
        {shown.map(([i, it], k) => (
          <Cell
            key={it.path}
            index={i}
            first={k === 0}
            path={it.path}
            name={it.name}
            edited={!!it.edited}
            info={it.info ?? null}
            selected={grid.sel.has(i)}
            onMove={move}
          />
        ))}
      </div>
    </main>
  );
}

let io: IntersectionObserver | null = null;
const ioTargets = new Map<Element, () => void>();
function observe(el: Element, cb: () => void): () => void {
  if (typeof IntersectionObserver !== 'function') {
    cb();
    return () => {};
  }
  io ??= new IntersectionObserver(
    (entries) => {
      for (const e of entries)
        if (e.isIntersecting) {
          ioTargets.get(e.target)?.();
          io?.unobserve(e.target);
          ioTargets.delete(e.target);
        }
    },
    { rootMargin: '200px' },
  );
  ioTargets.set(el, cb);
  io.observe(el);
  return () => {
    io?.unobserve(el);
    ioTargets.delete(el);
  };
}

const Cell = memo(function Cell(props: {
  index: number;
  first: boolean;
  path: string;
  name: string;
  edited: boolean;
  info: BadgeInfo | null;
  selected: boolean;
  onMove: (from: HTMLElement, dir: 1 | -1) => void;
}) {
  const t = useT();
  const { index, path, name, edited, info, selected } = props;
  const ref = useRef<HTMLDivElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [missing, setMissing] = useState<string | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let alive = true;
    const stop = observe(el, async () => {
      try {
        const r = await thumbnail(path);
        if (!alive) return;
        useLibraryStore.getState().updateThumb(path, r.edited, r.info);
        setSrc(URL.createObjectURL(r.blob));
      } catch (e) {
        if (alive) setMissing(explain((e as Error).message, t));
      }
    });
    return () => {
      alive = false;
      stop();
    };
  }, [path, t]);

  const lib = useLibraryStore.getState;
  const open = async () => {
    await lib().openPhoto(path);
    await lib().showGrid(false);
  };
  const badge = edited ? badgeTitle(info, t) : '';

  return (
    <div
      ref={ref}
      data-cell
      role="option"
      aria-selected={selected}
      tabIndex={props.first ? 0 : -1}
      className={clsx(css.cell, selected && css.selected, edited && css.edited, edited && stale(info) && css.stale)}
      title={edited ? `${path}\n${badge}` : path}
      onClick={(e) => lib().selectCell(index, { ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey })}
      onDoubleClick={() => void open()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          void open();
        } else if (e.key === ' ') {
          e.preventDefault();
          lib().selectCell(index, { ctrl: true });
        } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
          e.preventDefault();
          props.onMove(e.currentTarget, e.key === 'ArrowRight' ? 1 : -1);
        }
      }}
    >
      <div className={css.pic} title={missing ?? undefined}>
        {src ? (
          // 解碼後立刻釋放 bytes（S13 e）
          <img src={src} alt="" onLoad={() => URL.revokeObjectURL(src)} />
        ) : missing ? (
          <span className={css.missing}>{name}</span>
        ) : null}
      </div>
      <span className={css.mark} aria-hidden="true" title={badge} />
      <span className={css.nm}>{name}</span>
    </div>
  );
});
