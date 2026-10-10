/**
 * App 層的 UI 狀態（zustand）：toast、頂列狀態列、對話框（取代舊版的 prompt()／confirm()）。
 *
 * 舊版直接呼叫瀏覽器的 prompt()／confirm()；新版改成 MUI 對話框，但呼叫端的寫法維持「await 一個答案」：
 *   const name = await ask({title, initial});   // 取消＝null
 *   if (await confirmAsk({...})) …
 * 對話框本身由 components/common/AppDialogs 依這裡的狀態畫出來。
 */
import { create } from 'zustand';
import type { Translate } from '../domain/text';

export interface Toast {
  id: number;
  text: string;
  /** 原句（後端英文句子被說明成中文時，原句放提示） */
  title?: string;
  err?: boolean;
  action?: { label: string; run: () => void | Promise<void> };
  ms: number;
}

/** 狀態列的字用「怎麼翻」存（不是翻好的字），切換語言時狀態列跟著換。 */
export type Phrase = string | ((t: Translate) => string);

export interface StatusLine {
  text: Phrase;
  cls: 'idle' | 'busy' | 'err';
  title?: Phrase;
}

interface PromptState {
  kind: 'prompt' | 'confirm';
  title: string;
  label?: string;
  initial?: string;
  confirmLabel?: string;
  danger?: boolean;
  resolve: (v: string | null) => void;
}

interface AppState {
  toast: Toast | null;
  status: StatusLine;
  dialog: PromptState | null;
  showToast: (t: Omit<Toast, 'id' | 'ms'> & { ms?: number }) => void;
  hideToast: () => void;
  setStatus: (s: StatusLine) => void;
  closeDialog: (value: string | null) => void;
}

let toastSeq = 0;

export const useAppStore = create<AppState>((set, get) => ({
  toast: null,
  status: { text: '', cls: 'idle' },
  dialog: null,
  showToast: (t) => set({ toast: { ms: t.action ? 6000 : 2600, ...t, id: ++toastSeq } }),
  hideToast: () => set({ toast: null }),
  setStatus: (status) => set({ status }),
  closeDialog: (value) => {
    const d = get().dialog;
    set({ dialog: null });
    d?.resolve(value);
  },
}));

/** 簡寫：一般訊息／錯誤訊息。 */
export const toast = (text: string, err = false, title?: string) => useAppStore.getState().showToast({ text, err, title });

/** 帶一顆動作鈕的 toast（例如「復原」）。 */
export const toastAction = (text: string, label: string, run: () => void | Promise<void>) =>
  useAppStore.getState().showToast({ text, action: { label, run } });

export const setStatus = (text: Phrase, cls: StatusLine['cls'] = 'idle', title?: Phrase) =>
  useAppStore.getState().setStatus({ text, cls, title });

/** 問一個字串（取代 prompt()）：取消回 null。 */
export function ask(opts: { title: string; label?: string; initial?: string; confirmLabel?: string }): Promise<string | null> {
  return new Promise((resolve) => {
    useAppStore.getState().dialog?.resolve(null);
    useAppStore.setState({ dialog: { kind: 'prompt', ...opts, resolve } });
  });
}

/** 問是／否（取代 confirm()）。 */
export function confirmAsk(opts: { title: string; confirmLabel: string; danger?: boolean }): Promise<boolean> {
  return new Promise((resolve) => {
    useAppStore.getState().dialog?.resolve(null);
    useAppStore.setState({ dialog: { kind: 'confirm', ...opts, resolve: (v) => resolve(v !== null) } });
  });
}
