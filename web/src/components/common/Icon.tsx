/**
 * 線條圖示（DESIGN.md §6.3：15px、1.6 線寬、圓頭；舊版同款）。路徑直接從舊 index.html 搬來。
 * 不用 @mui/icons-material：整個介面只需要十幾個圖示，而且要跟舊版長得一樣。
 * 圖示一律 aria-hidden；按鈕自己負責 aria-label。
 */
import type { ReactNode } from 'react';

const PATHS: Record<string, ReactNode> = {
  menu: <path d="M2.5 4h11M2.5 8h11M2.5 12h11" />,
  prev: <path d="M10 3 5 8l5 5" />,
  next: <path d="m6 3 5 5-5 5" />,
  grid: (
    <>
      <rect x="2.5" y="2.5" width="4.5" height="4.5" rx=".8" />
      <rect x="9" y="2.5" width="4.5" height="4.5" rx=".8" />
      <rect x="2.5" y="9" width="4.5" height="4.5" rx=".8" />
      <rect x="9" y="9" width="4.5" height="4.5" rx=".8" />
    </>
  ),
  undo: (
    <>
      <path d="M6 4.5H3v-3" />
      <path d="M3 4.5a5.5 5.5 0 1 1-1 4" />
    </>
  ),
  redo: (
    <>
      <path d="M10 4.5h3v-3" />
      <path d="M13 4.5a5.5 5.5 0 1 0 1 4" />
    </>
  ),
  resetAll: (
    <>
      <path d="M5.5 3.5H2.5v-3" />
      <path d="M2.5 3.5A5.8 5.8 0 1 1 2 8" />
    </>
  ),
  original: (
    <>
      <rect x="2.5" y="2.5" width="11" height="11" rx="1.2" />
      <path d="M2.5 10.5 6 7l3 3 2-2 2.5 2.5" />
    </>
  ),
  sliders: (
    <>
      <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />
      <circle cx="10.5" cy="4.5" r="1.6" fill="var(--dr-bg-frame)" />
      <circle cx="5.5" cy="8" r="1.6" fill="var(--dr-bg-frame)" />
      <circle cx="9" cy="11.5" r="1.6" fill="var(--dr-bg-frame)" />
    </>
  ),
  settings: (
    <>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6l1.4 1.4M11 11l1.4 1.4M3.6 12.4 5 11M11 5l1.4-1.4" />
    </>
  ),
  chevron: <path d="m6 3.5 4.5 4.5L6 12.5" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  more: (
    <>
      <circle cx="3.5" cy="8" r=".9" fill="currentColor" />
      <circle cx="8" cy="8" r=".9" fill="currentColor" />
      <circle cx="12.5" cy="8" r=".9" fill="currentColor" />
    </>
  ),
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 15 }: { name: IconName; size?: number }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ display: 'block', flex: 'none' }}
    >
      {PATHS[name]}
    </svg>
  );
}
