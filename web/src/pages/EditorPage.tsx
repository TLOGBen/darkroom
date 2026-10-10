/**
 * 編輯頁（路由 /）：三欄編輯器，或縮圖格（取代三欄，頂列不變）；加上匯出對話框與全域快捷鍵。
 *
 * 進頁面時做的事（舊 app.js 的 init）：讀 preset 列表、滑桿表、旗標、群組樹（TanStack Query 自動），
 * 能力偵測在頁面就緒後才讀、永遠不擋畫面（E22）；第一次讀到時，照片庫或 GPU 關閉的原因寫到狀態列一次（E23）。
 * 頁面要關的時候，還沒送出的存檔用 keepalive 立刻送（seal F3）。
 */
import { useEffect, useRef } from 'react';
import { capLine, capReason } from '../domain/settings';
import { explain } from '../domain/errors';
import { useCapabilities, usePresetFlags, usePresetGroups, usePresets, useSliders } from '../hooks/queries';
import { setStatus, toast } from '../hooks/useAppStore';
import { useEditorKeyboard } from '../hooks/useEditorKeyboard';
import { useLibraryStore } from '../hooks/useLibraryStore';
import { useT } from '../hooks/useT';
import { EditorLayout } from '../layouts/EditorLayout';
import { PresetLibrary } from '../components/presets/PresetLibrary';
import { PreviewPane } from '../components/editor/PreviewPane';
import { SliderPanel } from '../components/editor/SliderPanel';
import { ThumbnailGrid } from '../components/library/ThumbnailGrid';
import { ExportDialog } from '../components/export/ExportDialog';

export function EditorPage() {
  const t = useT();
  const gridOpen = useLibraryStore((s) => s.gridOpen);
  const presets = usePresets();
  const sliders = useSliders();
  usePresetFlags();
  usePresetGroups();
  const caps = useCapabilities();
  useEditorKeyboard();

  // 載入失敗（後端沒開、preset 資料夾錯）：原句 toast 一次
  const loadError = presets.error ?? sliders.error;
  useEffect(() => {
    if (loadError) toast(t('app.loadFailed', { reason: explain(loadError.message, t) }), true, loadError.message);
  }, [loadError, t]);

  // E23：照片庫／GPU 關閉的原因寫到狀態列一次
  const capsShown = useRef(false);
  useEffect(() => {
    if (!caps.data || capsShown.current) return;
    capsShown.current = true;
    const off = capReason(caps.data, 'photo_library') !== null ? 'photo_library' : capReason(caps.data, 'gpu') !== null ? 'gpu' : null;
    if (off) setStatus((tt) => capLine(off, caps.data?.[off], tt), off === 'photo_library' ? 'err' : 'idle');
  }, [caps.data, t]);

  // seal F3：頁面關掉前把排隊與退避中的存檔送出去
  useEffect(() => {
    const onUnload = () => useLibraryStore.getState().unload();
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, []);

  return (
    <>
      {gridOpen ? (
        <ThumbnailGrid />
      ) : (
        <EditorLayout library={<PresetLibrary />} preview={<PreviewPane />} sliders={<SliderPanel />} />
      )}
      <ExportDialog />
    </>
  );
}
