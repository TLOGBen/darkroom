/**
 * 兩份語言檔的鍵完全一致（plan-v2 任務：所有 UI 字串走 t()，zh-TW 與 en-US 不能少任何一個鍵），
 * 而且每個 {{插值}} 的名字兩邊相同（少一個變數，句子就會出現原樣的 {{x}}）。
 */
import { describe, expect, test } from 'vitest';
import zhTW from './locales/zh-TW.json';
import enUS from './locales/en-US.json';

type Tree = { [k: string]: string | Tree };

function flatten(tree: Tree, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(tree)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (typeof v === 'string') out[key] = v;
    else Object.assign(out, flatten(v, key));
  }
  return out;
}

const vars = (s: string) => [...s.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]).sort();

describe('locales', () => {
  const zh = flatten(zhTW as Tree);
  const en = flatten(enUS as Tree);

  test('zh-TW 與 en-US 的鍵集合完全相同', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort());
  });

  test('每個鍵兩邊的插值變數相同', () => {
    for (const key of Object.keys(zh)) expect([key, vars(en[key] ?? '')]).toEqual([key, vars(zh[key])]);
  });

  test('沒有空字串', () => {
    for (const [k, v] of Object.entries({ ...zh, ...en })) expect([k, v.length > 0]).toEqual([k, true]);
  });
});
