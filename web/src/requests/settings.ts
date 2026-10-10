/**
 * 設定與能力 context 的 HTTP 請求（形狀照 plan-v2 §3）：設定讀寫、匯出／匯入、版本、能力偵測。
 * PUT／import 是「全部驗證通過才寫」，失敗時 ApiError 的 message 是後端原句，設定頁顯示在對應欄位。
 */
import type { Capabilities, Settings, SettingsApplyResult, SettingsExport, SettingsResponse, VersionInfo } from '../domain/settings';
import { apiJson, withQuery } from './client';

export const getSettings = () => apiJson<SettingsResponse>('GET', '/api/settings');
/**
 * 部分更新：body 是 {values: {扁平鍵: 值}}（後端 adapters/http/server.py 的 api_settings_set 讀 body.values；
 * CLI 的 settings set KEY=VALUE、MCP 的 darkroom_settings_set 也是同一個 values 參數）。
 */
export const putSettings = (patch: Settings) =>
  apiJson<SettingsApplyResult>('PUT', '/api/settings', { values: patch });
export const exportSettings = () => apiJson<SettingsExport>('GET', '/api/settings/export');
/**
 * 匯入：後端的匯入操作收「document 或 path 恰好一個」（domain/messages.py SET_IMPORT_SOURCE）；
 * 透過 HTTP 不送路徑，所以一律送 {document}。
 */
export const importSettings = (document: SettingsExport) =>
  apiJson<SettingsApplyResult>('POST', '/api/settings/import', { document });
export const getVersion = () => apiJson<VersionInfo>('GET', '/api/version');
export const capabilities = (refresh = false) =>
  apiJson<{ features: Capabilities }>('GET', withQuery('/api/capabilities', { refresh: refresh ? 1 : undefined }));
