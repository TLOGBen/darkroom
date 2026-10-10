/**
 * 編輯頁的頂列：收起左欄｜品牌｜照片路徑＋開啟｜上一張 位置 下一張｜縮圖格｜沿用中提示｜…｜復原 重做｜
 * 還原全部微調｜還原成原圖｜狀態列｜能力｜設定｜收起右欄。順序與文字照舊 index.html。
 *
 * 資料：開著的照片與資料夾位置來自 useLibraryStore；復原／重做與「沿用中」來自 useEditStore；
 * 停用的按鈕 title 寫原因（照片庫關閉時「取回上一份」等）。
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { IconButton, TextField, Tooltip, useMediaQuery } from '@mui/material';
import { carryHintVisible } from '../../domain/edit';
import { useEditStore, editSelectors } from '../../hooks/useEditStore';
import { useLibraryStore } from '../../hooks/useLibraryStore';
import { useLayoutStore } from '../../hooks/useLayoutStore';
import { useT } from '../../hooks/useT';
import { loadPref } from '../../utils/storage';
import { Icon } from '../common/Icon';
import { ToolButton } from '../common/ToolButton';
import { CapabilitiesButton, StatusLine } from '../common/StatusBar';
import css from './EditorTopBar.module.scss';

export function EditorTopBar() {
  const t = useT();
  const nav = useNavigate();
  const narrow = useMediaQuery('(max-width: 960px)');
  const image = useLibraryStore((s) => s.image);
  const folder = useLibraryStore((s) => s.folder);
  const hasEdit = useLibraryStore((s) => !!s.edit);
  const gridOpen = useLibraryStore((s) => s.gridOpen);
  const ed = useEditStore((s) => s.ed);
  const canUndo = useEditStore(editSelectors.canUndo);
  const canRedo = useEditStore(editSelectors.canRedo);
  const [path, setPath] = useState('');

  // S15：?path= 只填進框裡（瀏覽器外來的連結不能讓 App 讀路徑）；沒有就還原上次開的照片（跟舊版一樣）
  useEffect(() => {
    const q = new URLSearchParams(location.search).get('path');
    const last = loadPref<string>('lastPath', '');
    if (q) setPath(q);
    else if (last && !useLibraryStore.getState().image) {
      setPath(last);
      void useLibraryStore.getState().openPhoto(last);
    }
  }, []);
  // 開了別張（上一張／下一張、縮圖格點兩下）時，框裡的路徑跟著換
  useEffect(() => {
    if (image) setPath(image.path);
  }, [image]);

  const pos = folder && folder.index >= 0 ? folder : null;
  const positionText = pos
    ? t('topbar.position', { n: pos.index + 1, total: pos.files.length, name: pos.files[pos.index].name })
    : image
      ? image.path
      : t('topbar.noPhoto');
  const carry = carryHintVisible(ed, !!image, hasEdit);

  return (
    <>
      <IconButton
        aria-label={t('topbar.toggleLib')}
        title={t('topbar.toggleLib')}
        onClick={() => useLayoutStore.getState().toggleLib(narrow)}
      >
        <Icon name="menu" />
      </IconButton>
      <span className={css.brand}>{t('app.name')}</span>
      <form
        className={css.open}
        autoComplete="off"
        onSubmit={(e) => {
          e.preventDefault();
          void useLibraryStore.getState().openPhoto(path);
        }}
      >
        <TextField
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder={t('topbar.pathPlaceholder')}
          className={css.path}
          slotProps={{ htmlInput: { 'aria-label': t('topbar.pathLabel'), spellCheck: false, className: 'dr-mono' } }}
        />
        <ToolButton type="submit" label={t('topbar.open')} collapsible={false} />
      </form>
      <span className={css.seg}>
        <IconButton aria-label={t('topbar.prev')} title={t('topbar.prev')} disabled={!pos || pos.index <= 0} onClick={() => useLibraryStore.getState().step(-1)}>
          <Icon name="prev" />
        </IconButton>
        <span className={css.position} title={pos ? pos.files[pos.index].path : undefined}>
          {positionText}
        </span>
        <IconButton
          aria-label={t('topbar.next')}
          title={t('topbar.next')}
          disabled={!pos || pos.index >= pos.files.length - 1}
          onClick={() => useLibraryStore.getState().step(1)}
        >
          <Icon name="next" />
        </IconButton>
      </span>
      <ToolButton
        icon="grid"
        label={t('topbar.grid')}
        title={t('topbar.gridTitle')}
        pressed={gridOpen}
        onClick={() => void useLibraryStore.getState().showGrid(!gridOpen)}
      />
      {carry && (
        <Tooltip title={t('topbar.carryHint')}>
          <span className={css.hint}>{narrow ? t('topbar.carryHintShort') : t('topbar.carryHint')}</span>
        </Tooltip>
      )}
      <span className={css.sp} />
      <span className={css.seg}>
        <IconButton aria-label={t('topbar.undo')} title={t('topbar.undo')} disabled={!canUndo} onClick={() => useEditStore.getState().undo()}>
          <Icon name="undo" />
        </IconButton>
        <IconButton aria-label={t('topbar.redo')} title={t('topbar.redo')} disabled={!canRedo} onClick={() => useEditStore.getState().redo()}>
          <Icon name="redo" />
        </IconButton>
      </span>
      <ToolButton
        icon="resetAll"
        label={t('topbar.resetAll')}
        title={t('topbar.resetAllTitle')}
        onClick={() => void useEditStore.getState().dispatch({ type: 'resetAll' })}
      />
      <ToolButton
        icon="original"
        label={t('topbar.resetOriginal')}
        title={t('topbar.resetOriginalTitle')}
        disabled={!image}
        onClick={() => void useLibraryStore.getState().resetOriginal()}
      />
      <StatusLine />
      <CapabilitiesButton />
      <IconButton aria-label={t('app.nav.settingsTitle')} title={t('app.nav.settingsTitle')} onClick={() => nav('/settings')}>
        <Icon name="settings" />
      </IconButton>
      <IconButton
        aria-label={t('topbar.toggleSliders')}
        title={t('topbar.toggleSliders')}
        onClick={() => useLayoutStore.getState().toggleSliders()}
      >
        <Icon name="sliders" />
      </IconButton>
    </>
  );
}
