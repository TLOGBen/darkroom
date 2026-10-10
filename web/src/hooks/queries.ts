/**
 * 伺服器資料（TanStack Query）：唯一的 QueryClient、所有 query key，以及每個 context 讀資料用的 hooks。
 *
 * 為什麼 QueryClient 放在模組層：編輯器的 zustand store（非 React 程式）也要讀同一份資料
 * （例如自動存檔時要知道能力偵測說照片庫能不能寫、選 preset 時要 preset 的名字），
 * 所以 store 直接 `queryClient.getQueryData(keys.presets)`；React 元件用下面的 hooks，兩邊看的是同一份快取。
 *
 * 資料什麼時候重讀：preset 庫寫入成功後 `invalidatePresetLibrary()`；設定套用成功後 `invalidateAfterSettings()`
 * （設定改了資料夾，preset 列表、滑桿、能力都可能不同）。
 */
import { QueryClient, useQuery } from '@tanstack/react-query';
import type { Preset, PresetFlags, PresetGroups } from '../domain/preset';
import type { Slider, SliderTable } from '../domain/edit';
import type { Capabilities } from '../domain/settings';
import * as presetReq from '../requests/presets';
import * as editReq from '../requests/edits';
import * as exportReq from '../requests/exports';
import * as settingsReq from '../requests/settings';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 本機伺服器：不需要背景輪詢或視窗聚焦時重抓（會打斷正在看的畫面）；資料改了由寫入的地方主動失效。
      staleTime: Infinity,
      refetchOnWindowFocus: false,
      retry: false,
    },
  },
});

export const keys = {
  presets: ['presets'] as const,
  presetFlags: ['presets', 'flags'] as const,
  presetGroups: ['presets', 'groups'] as const,
  sliders: ['sliders'] as const,
  capabilities: ['capabilities'] as const,
  exportPresets: ['exportPresets'] as const,
  settings: ['settings'] as const,
  version: ['version'] as const,
};

// ---- Preset 庫 ----------------------------------------------------------------------------------------------------
export const usePresets = () => useQuery({ queryKey: keys.presets, queryFn: presetReq.listPresets });
export const usePresetFlags = () => useQuery({ queryKey: keys.presetFlags, queryFn: presetReq.presetFlags });
export const usePresetGroups = () => useQuery({ queryKey: keys.presetGroups, queryFn: presetReq.presetGroups });

/** 改名、搬移、最愛、匯入、存成 preset 之後：列表、旗標、群組樹一起重讀。 */
export const invalidatePresetLibrary = () => queryClient.invalidateQueries({ queryKey: ['presets'] });

export const presetsById = (): Record<string, Preset> =>
  Object.fromEntries((queryClient.getQueryData<Preset[]>(keys.presets) ?? []).map((p) => [p.id, p]));
export const presetFlagsNow = (): PresetFlags => queryClient.getQueryData<PresetFlags>(keys.presetFlags) ?? {};
export const presetGroupsNow = (): PresetGroups | undefined => queryClient.getQueryData<PresetGroups>(keys.presetGroups);

// ---- 編輯（滑桿表） -------------------------------------------------------------------------------------------------
export const useSliders = () => useQuery({ queryKey: keys.sliders, queryFn: editReq.sliderTable });
export const slidersByKey = (): Record<string, Slider> =>
  Object.fromEntries((queryClient.getQueryData<SliderTable>(keys.sliders)?.sliders ?? []).map((s) => [s.key, s]));

// ---- 匯出預設 ------------------------------------------------------------------------------------------------------
export const useExportPresets = (enabled = true) =>
  useQuery({ queryKey: keys.exportPresets, queryFn: async () => (await exportReq.listExportPresets()).presets, enabled });

// ---- 設定與能力 -----------------------------------------------------------------------------------------------------
/** 能力偵測：頁面就緒後才讀，永遠不擋畫面（E22）。refresh 由 CapabilitiesButton 呼叫 `refreshCapabilities`。 */
export const useCapabilities = () =>
  useQuery({ queryKey: keys.capabilities, queryFn: async () => (await settingsReq.capabilities(false)).features });
export const capabilitiesNow = (): Capabilities | null =>
  queryClient.getQueryData<Capabilities>(keys.capabilities) ?? null;
export async function refreshCapabilities(): Promise<Capabilities> {
  const features = (await settingsReq.capabilities(true)).features;
  queryClient.setQueryData(keys.capabilities, features);
  return features;
}

export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: settingsReq.getSettings });
export const useVersion = () => useQuery({ queryKey: keys.version, queryFn: settingsReq.getVersion });

/** 設定套用成功：資料夾可能換了，所有伺服器資料重讀（能力也重測）。 */
export async function invalidateAfterSettings(): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: keys.settings });
  await queryClient.invalidateQueries({ queryKey: ['presets'] });
  await queryClient.invalidateQueries({ queryKey: keys.sliders });
  await queryClient.invalidateQueries({ queryKey: keys.exportPresets });
  try {
    await refreshCapabilities();
  } catch {
    await queryClient.invalidateQueries({ queryKey: keys.capabilities });
  }
}
