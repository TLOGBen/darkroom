/**
 * 介面語言怎麼決定（plan-v2 §2：設定的 language → 瀏覽器語言 → zh-TW）。
 *
 * 後端 GET /api/settings 會把預設值合併進 settings，沒設 language 時也回 "zh-TW"、sources.language＝"default"；
 * configuredLanguage 只認使用者真的設定過的值，沒設定過回 null，讓瀏覽器語言／上次記住的語言保留下來。
 */
import { describe, expect, test } from 'vitest';
import { configuredLanguage, pickLanguage } from '../settings';

describe('configuredLanguage', () => {
  test('a default zh-TW is not the user choosing zh-TW', () => {
    expect(configuredLanguage({ settings: { language: 'zh-TW' }, sources: { language: 'default' } })).toBeNull();
  });

  test('a language written in the settings file (or the environment) wins', () => {
    expect(configuredLanguage({ settings: { language: 'en-US' }, sources: { language: 'file' } })).toBe('en-US');
    expect(configuredLanguage({ settings: { language: 'zh-TW' }, sources: { language: 'env' } })).toBe('zh-TW');
  });

  test('nothing read yet, no source, or an unknown value: keep the current language', () => {
    expect(configuredLanguage(undefined)).toBeNull();
    expect(configuredLanguage({ settings: { language: 'en-US' }, sources: {} })).toBeNull();
    expect(configuredLanguage({ settings: { language: 'fr-FR' }, sources: { language: 'file' } })).toBeNull();
  });

  test('with no configured language an English browser gets English', () => {
    const res = { settings: { language: 'zh-TW' }, sources: { language: 'default' as const } };
    expect(configuredLanguage(res) ?? pickLanguage(null, ['en-GB', 'zh-TW'])).toBe('en-US');
  });
});
