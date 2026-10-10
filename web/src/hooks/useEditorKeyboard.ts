/**
 * 編輯頁的全域快捷鍵（照舊 app.js 的 document keydown／keyup，一個都不少）：
 *
 *   Ctrl+Z／Ctrl+Shift+Z／Ctrl+Y   復原／重做（裁切模式中只動草稿）
 *   Ctrl+[／Ctrl+]                  向左／向右轉 90°（裁切模式內外都可以）
 *   ← ／ →                          上一張／下一張（焦點在輸入框、樹、縮圖格時不管）
 *   \（按住）                       看原圖；放開、視窗失焦、分頁切走就回來
 *   Y                               A/B 對照（裁切中不能用）
 *   R                               進入／完成裁切
 *   裁切模式：Enter 完成、Esc 取消、X 直式／橫式互換
 *   Esc                             關掉「套不上的設定」全文
 * 對話框開著時（匯出、詢問）鍵盤歸對話框；在文字框裡打字時字母鍵不觸發。
 */
import { useEffect } from 'react';
import { AB_KEY } from '../domain/edit';
import { useAppStore } from './useAppStore';
import { useEditStore } from './useEditStore';
import { useExportStore } from './useExportStore';
import { useLibraryStore } from './useLibraryStore';

const typing = (el: EventTarget | null) =>
  el instanceof HTMLElement &&
  (el.matches('input[type=text], input[type=search], input[type=number], input:not([type]), textarea') || el.isContentEditable);
const inField = (el: EventTarget | null) => el instanceof HTMLElement && el.matches('input, select, textarea, [role=combobox]');
const plain = (e: KeyboardEvent) => !e.ctrlKey && !e.metaKey && !e.altKey;

/** 裁切模式的鍵；回 true＝是我們的鍵。 */
function cropKey(e: KeyboardEvent): boolean {
  const es = useEditStore.getState();
  const k = e.key.toLowerCase();
  if (e.key === 'Escape') {
    e.preventDefault();
    void es.leaveCrop(false);
    return true;
  }
  if (e.key === 'Enter' && !(e.target instanceof HTMLElement && e.target.matches('button, select, input, [role=combobox], [role=option]'))) {
    e.preventDefault();
    void es.leaveCrop(true);
    return true;
  }
  if ((e.ctrlKey || e.metaKey) && k === 'z') {
    e.preventDefault();
    es.cropStep(e.shiftKey ? 'redo' : 'undo');
    return true;
  }
  if ((e.ctrlKey || e.metaKey) && k === 'y') {
    e.preventDefault();
    es.cropStep('redo');
    return true;
  }
  if (typing(e.target)) return false;
  const d = es.crop?.draft;
  if (k === 'x' && plain(e) && d && d.aspect !== 'free' && d.aspect !== '1:1') {
    es.geometryAct('orient');
    return true;
  }
  if (k === AB_KEY) return true; // C25：裁切中沒有對照
  return false;
}

export function useEditorKeyboard(): void {
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const es = useEditStore.getState();
      if (useExportStore.getState().open || useAppStore.getState().dialog) return; // 對話框拿走鍵盤
      if (document.querySelector('.MuiPopover-root, .MuiMenu-root')) return; // 選單／彈出框開著
      if (e.key === 'Escape' && es.skipOpen) {
        es.setSkipOpen(false);
        return;
      }
      if (es.cropActive() && cropKey(e)) return;
      if (typing(e.target)) return;
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && (e.key === '[' || e.key === ']')) {
        e.preventDefault();
        es.geometryAct(e.key === '[' ? 'rotate_left' : 'rotate_right');
        return;
      }
      if ((e.ctrlKey || e.metaKey) && k === 'z') {
        e.preventDefault();
        if (e.shiftKey) es.redo();
        else es.undo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && k === 'y') {
        e.preventDefault();
        es.redo();
        return;
      }
      const t = e.target as HTMLElement | null;
      if (t?.closest?.('[role=tree], [data-grid]')) return; // 樹與縮圖格有自己的方向鍵
      if (k === AB_KEY && plain(e) && !e.shiftKey && !e.repeat) {
        void es.abToggle();
        return;
      }
      if (k === 'r' && plain(e) && !e.shiftKey && !e.repeat) {
        if (es.cropActive()) void es.leaveCrop(true);
        else es.enterCrop();
        return;
      }
      if (e.key === '\\' && !e.repeat) void es.showOriginal(true);
      else if (e.key === 'ArrowLeft' && !inField(e.target) && !e.repeat) useLibraryStore.getState().step(-1);
      else if (e.key === 'ArrowRight' && !inField(e.target) && !e.repeat) useLibraryStore.getState().step(1);
    };
    const up = (e: KeyboardEvent) => {
      if (e.key === '\\' && useEditStore.getState().holding) void useEditStore.getState().showOriginal(false);
    };
    document.addEventListener('keydown', down);
    document.addEventListener('keyup', up);
    return () => {
      document.removeEventListener('keydown', down);
      document.removeEventListener('keyup', up);
    };
  }, []);
}
