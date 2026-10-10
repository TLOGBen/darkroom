/**
 * 整個 App 的外框：頂列（44px）＋目前路由的頁面＋全域的 toast 與對話框。
 *
 * 頂列依路由換內容：編輯頁是完整的編輯工具（開啟、上一張／下一張、縮圖格、復原／重做、還原…，見 EditorTopBar）；
 * 設定頁只有品牌、回到編輯、狀態列與能力按鈕。兩邊都有通往另一頁的入口（plan-v2 任務：頂列有設定頁入口）。
 * 編輯器的狀態放在 zustand store 裡，所以去設定頁再回來，開著的照片與編輯都還在。
 */
import { Outlet, useLocation, useNavigate } from 'react-router';
import { Button } from '@mui/material';
import { AppDialogs } from '../components/common/AppDialogs';
import { ToastHost } from '../components/common/ToastHost';
import { CapabilitiesButton, StatusLine } from '../components/common/StatusBar';
import { Icon } from '../components/common/Icon';
import { EditorTopBar } from '../components/editor/EditorTopBar';
import { useT } from '../hooks/useT';
import css from './AppLayout.module.scss';

export function AppLayout() {
  const t = useT();
  const loc = useLocation();
  const nav = useNavigate();
  const onSettings = loc.pathname.startsWith('/settings');
  return (
    <div className={css.app}>
      <header className={css.bar}>
        {onSettings ? (
          <>
            <span className={css.brand}>{t('app.name')}</span>
            <Button startIcon={<Icon name="prev" />} onClick={() => nav('/')}>
              {t('settings.back')}
            </Button>
            <span className={css.sp} />
            <StatusLine />
            <CapabilitiesButton />
          </>
        ) : (
          <EditorTopBar />
        )}
      </header>
      <div className={css.body}>
        <Outlet />
      </div>
      <ToastHost />
      <AppDialogs />
    </div>
  );
}
