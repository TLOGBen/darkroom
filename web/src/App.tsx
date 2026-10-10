/**
 * 路由：/ 編輯頁、/settings 設定頁（兩頁共用 AppLayout 的頂列）；其他路徑回編輯頁。
 * 進 App 時讀一次設定，讓介面語言照設定（設定 → 瀏覽器語言 → zh-TW，plan-v2 §2）；讀不到設定也照常用。
 */
import { useEffect } from 'react';
import { Navigate, Route, Routes } from 'react-router';
import { configuredLanguage } from './domain/settings';
import { useSettings } from './hooks/queries';
import { setLanguage } from './i18n';
import { AppLayout } from './layouts/AppLayout';
import { EditorPage } from './pages/EditorPage';
import { SettingsPage } from './pages/SettingsPage';

export function App() {
  const settings = useSettings();
  useEffect(() => {
    // 只有使用者真的設定過才切（沒設定時後端回的 zh-TW 是預設值，不能蓋掉瀏覽器語言／上次記住的語言）
    const lang = configuredLanguage(settings.data);
    if (lang) setLanguage(lang);
  }, [settings.data]);

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<EditorPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
