/**
 * 編輯器的三欄版面（DESIGN.md §5）：左 preset 庫（280／230）｜中 預覽（最大）｜右 滑桿（390／340／290）。
 * 兩側欄可以收起（頂列的兩顆按鈕）；窄視窗（≤960）時 preset 欄收成蓋在預覽上的抽屜。
 * 這裡只管版面，內容由 EditorPage 塞進三個 slot。
 */
import type { ReactNode } from 'react';
import { Drawer, useMediaQuery } from '@mui/material';
import { useLayoutStore } from '../hooks/useLayoutStore';
import css from './EditorLayout.module.scss';

export function EditorLayout({ library, preview, sliders }: { library: ReactNode; preview: ReactNode; sliders: ReactNode }) {
  const narrow = useMediaQuery('(max-width: 960px)');
  const libCollapsed = useLayoutStore((s) => s.libCollapsed);
  const slCollapsed = useLayoutStore((s) => s.slCollapsed);
  const drawerOpen = useLayoutStore((s) => s.libDrawerOpen);
  return (
    <main className={css.editor}>
      {narrow ? (
        <Drawer
          open={drawerOpen}
          onClose={() => useLayoutStore.getState().setLibDrawer(false)}
          slotProps={{ paper: { className: css.drawer } }}
        >
          {library}
        </Drawer>
      ) : (
        !libCollapsed && <div className={css.lib}>{library}</div>
      )}
      <div className={css.center}>{preview}</div>
      {!slCollapsed && <div className={css.sl}>{sliders}</div>}
    </main>
  );
}
