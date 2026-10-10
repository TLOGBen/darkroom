/**
 * 按住看原圖：手上的原圖預覽只在「同一張照片、同一個幾何」時才能顯示（驗收發現：換照片後第一次按住，
 * 畫面先閃出上一張的原圖並標「原圖」，原圖請求失敗時就一直停在錯的照片）。
 * PreviewPane 用 originalIsCurrent() 決定顯示原圖還是繼續顯示預覽；這裡直接測 store 的判斷。
 */
import { afterEach, describe, expect, test } from 'vitest';
import { originalKey } from '../../domain/geometry';
import { useEditStore } from '../useEditStore';
import { useLibraryStore } from '../useLibraryStore';

type Image = ReturnType<typeof useLibraryStore.getState>['image'];
const image = (id: string) => ({ image_id: id, width: 300, height: 200, preview_width: 300, preview_height: 200 }) as unknown as Image;

afterEach(() => {
  useLibraryStore.setState({ image: null as Image });
  useEditStore.setState({ originalUrl: null, originalFor: null, holding: false, crop: null });
});

describe('originalIsCurrent', () => {
  test('the original of the photo on screen is shown; after switching photos it is not', () => {
    useLibraryStore.setState({ image: image('p0') });
    useEditStore.setState({ crop: null });
    const g = useEditStore.getState().ed.geometry;
    useEditStore.setState({ originalUrl: 'blob:p0', originalFor: originalKey('p0', g, false), holding: true });
    expect(useEditStore.getState().originalIsCurrent()).toBe(true);

    useLibraryStore.setState({ image: image('p2') }); // 換照片：新的原圖還沒算好
    expect(useEditStore.getState().originalIsCurrent()).toBe(false);
  });

  test('no photo or no original: never current', () => {
    expect(useEditStore.getState().originalIsCurrent()).toBe(false);
    useLibraryStore.setState({ image: image('p0') });
    expect(useEditStore.getState().originalIsCurrent()).toBe(false);
  });
});
