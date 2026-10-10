/**
 * 版面狀態（zustand）：左欄（preset 庫）與右欄（滑桿）的收起／展開、窄視窗時 preset 抽屜是否打開、照片底色。
 * 照片底色寫到 <html data-canvas>（global.scss 依它切 --dr-canvas），記在 localStorage `darkroom.canvas`（跟舊版同一個鍵）。
 */
import { create } from 'zustand';
import { CANVAS_STORAGE_KEY, canvasFrom, type Canvas } from '../domain/edit';
import { loadPref, savePref } from '../utils/storage';

interface LayoutState {
  libCollapsed: boolean;
  slCollapsed: boolean;
  libDrawerOpen: boolean;
  canvas: Canvas;
  toggleLib: (narrow: boolean) => void;
  toggleSliders: () => void;
  setLibDrawer: (open: boolean) => void;
  setCanvas: (c: string) => void;
}

const applyCanvas = (c: Canvas) => {
  if (typeof document !== 'undefined') document.documentElement.dataset.canvas = c;
};

const initialCanvas = canvasFrom(loadPref<string>(CANVAS_STORAGE_KEY.replace(/^darkroom\./, ''), 'dark'));
applyCanvas(initialCanvas);

export const useLayoutStore = create<LayoutState>((set, get) => ({
  libCollapsed: false,
  slCollapsed: false,
  libDrawerOpen: false,
  canvas: initialCanvas,
  toggleLib: (narrow) => (narrow ? set({ libDrawerOpen: !get().libDrawerOpen }) : set({ libCollapsed: !get().libCollapsed })),
  toggleSliders: () => set({ slCollapsed: !get().slCollapsed }),
  setLibDrawer: (libDrawerOpen) => set({ libDrawerOpen }),
  setCanvas(name) {
    const c = canvasFrom(name);
    applyCanvas(c);
    savePref('canvas', c);
    set({ canvas: c });
  },
}));
