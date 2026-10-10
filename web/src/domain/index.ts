/**
 * 前端領域層的總入口：依 bounded context 分檔（preset、edit＋geometry、library、export、settings），
 * 這裡全部重新匯出，讓測試與少數需要跨 context 的地方可以 `import * as L from '../domain'`（跟舊 logic.js 的 L 同名同形）。
 * 元件請直接從各自的 context 檔匯入，依賴比較清楚。
 */
export * from './text';
export * from './geometry';
export * from './edit';
export * from './preset';
export * from './library';
export * from './export';
export * from './settings';
export * from './errors';
