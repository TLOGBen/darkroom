/**
 * 自動存檔（PL15、S13 g／g'、C29）。取代舊 tests/js/test_logic.cjs 最後一段「在假 DOM 裡跑 app.js」：
 * 新前端沒有 app.js，同一條路徑改由 zustand store（useLibraryStore／useEditStore）＋AutosaveQueue 跑，
 * fetch 換成假的、只記錄送了什麼。
 *
 * C29（S3 封緘）：讀不到已存編輯的照片，動了滑桿、轉了 90° 之後，什麼取代已存編輯的請求都不能送
 * （沒有 PUT /api/edit、沒有 POST /api/edit/paste），畫面要說原因；對照組（讀得到）同樣的動作會送出一次。
 */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { AutosaveQueue } from '../autosave';
import { AUTOSAVE_MS, EDIT_UNREADABLE, SAVE_RETRY_MS, saveAllowed } from '../../domain/library';
import type { EditRequest } from '../../domain/edit';
import { keys, queryClient } from '../queries';
import { useEditStore } from '../useEditStore';
import { useLibraryStore } from '../useLibraryStore';
import { initialEditor } from '../../domain/edit';

interface Call {
  method: string;
  url: string;
  body?: string;
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function fakeServer(editAnswer: () => Response) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
    const method = init.method ?? 'GET';
    calls.push({ method, url, body: typeof init.body === 'string' ? init.body : undefined });
    if (url === '/api/open') return json(200, { image_id: 'i1', width: 300, height: 200, preview_width: 300, preview_height: 200 });
    if (url.startsWith('/api/folder')) return json(200, { folder: 'F', files: [], index: -1 });
    if (url.startsWith('/api/edit?')) return editAnswer();
    if (url === '/api/preview') return new Response(new Blob(['x'], { type: 'image/jpeg' }), { status: 200 });
    if (url === '/api/edit' && method === 'PUT') return json(200, { fingerprint: 'f', edit: { preset: null }, preset_status: null });
    return json(200, { results: [] });
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

const replaces = (calls: Call[]) =>
  calls.filter((c) => (c.method === 'PUT' && c.url === '/api/edit') || (c.method === 'POST' && c.url === '/api/edit/paste'));

async function runPage(editAnswer: () => Response) {
  const calls = fakeServer(editAnswer);
  await useLibraryStore.getState().openPhoto('D:/p/a.jpg');
  calls.length = 0;
  await useEditStore.getState().setValue('Contrast2012', 30); // 使用者動了滑桿
  await useEditStore.getState().dispatch({
    type: 'setGeometry',
    geometry: { rotate: 90, flip: false, angle: 0, aspect: 'original', crop: null },
  });
  await new Promise((r) => setTimeout(r, AUTOSAVE_MS + 50));
  await useLibraryStore.getState().flushAll();
  return { calls, lib: useLibraryStore.getState() };
}

describe('C29 (seal): a saved edit that could not be read is never replaced by the autosave', () => {
  beforeEach(() => {
    queryClient.setQueryData(keys.sliders, {
      sliders: [{ key: 'Contrast2012', group: 'basic', label: '對比', min: -100, max: 100, default: 0, step: 1, hue: false }],
      groups: [['basic', '基本']],
    });
    queryClient.setQueryData(keys.capabilities, {});
    vi.stubGlobal(
      'Image',
      class {
        onload: (() => void) | null = null;
        set src(_v: string) {
          setTimeout(() => this.onload?.(), 0);
        }
      },
    );
    URL.createObjectURL = () => 'blob:x';
    URL.revokeObjectURL = () => {};
    useEditStore.setState({ ed: initialEditor(), detail: null });
    useLibraryStore.setState({ image: null, edit: null, editUnreadable: null, snapshots: {} });
  });
  afterEach(() => vi.unstubAllGlobals());

  test('unreadable edit: nothing that replaces it is sent, and the screen says why', async () => {
    const failed = await runPage(() => json(503, { error: '照片庫的編輯檔損壞：x' }));
    expect(replaces(failed.calls)).toEqual([]);
    expect(failed.lib.editUnreadable).toBe('D:/p/a.jpg');
    expect(useLibraryStore.getState().editStatusText()).toBe(EDIT_UNREADABLE);
  });

  test('control: a readable edit -> the very same moves are saved once, with the geometry', async () => {
    const ok = await runPage(() => json(200, { fingerprint: 'f', edit: null, preset_status: null, previous: false }));
    const sent = replaces(ok.calls);
    expect(sent.length).toBe(1);
    expect(JSON.parse(sent[0].body as string).geometry.rotate).toBe(90);
    expect(EDIT_UNREADABLE).toBe(
      '讀不到已存的編輯：這張的修改先不會自動存檔（以免蓋掉原本存的裁切與顏色），請重新開啟這張照片',
    );
    expect(saveAllowed('a', 'a')).toBe(false);
    expect(saveAllowed(null, 'a')).toBe(true);
    expect(saveAllowed('a', 'b')).toBe(true);
  });
});

describe('AutosaveQueue: latest wins, one retry, nothing left behind (S13 g／g\')', () => {
  const req = (n: number): EditRequest => ({
    method: 'PUT',
    body: { path: 'A', preset_id: null, strength: 100, overrides: { Contrast2012: n }, geometry: null },
  });

  test('only the newest state of a burst is sent', async () => {
    vi.useFakeTimers();
    const sent: number[] = [];
    const q = new AutosaveQueue({
      send: async (job) => {
        sent.push((job.req.body as { overrides: Record<string, number> }).overrides.Contrast2012);
        return { edit: null };
      },
      onSaved: () => {},
      onError: () => {},
    });
    q.schedule({ path: 'A', req: req(1) });
    q.schedule({ path: 'A', req: req(2) });
    q.schedule({ path: 'A', req: req(3) });
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS + 1);
    expect(sent).toEqual([3]);
    vi.useRealTimers();
  });

  test('a failed save is retried once after the back-off; a newer change supersedes it', async () => {
    vi.useFakeTimers();
    let fail = true;
    const sent: number[] = [];
    const errors: string[] = [];
    const q = new AutosaveQueue({
      send: async (job) => {
        sent.push((job.req.body as { overrides: Record<string, number> }).overrides.Contrast2012);
        if (fail) throw new Error('disk full');
        return { edit: null };
      },
      onSaved: () => {},
      onError: (m) => errors.push(m),
    });
    q.schedule({ path: 'A', req: req(1) });
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS + 1);
    expect(errors).toEqual(['disk full']);
    expect(q.snapshot().retries).toEqual(['A']);
    expect(q.dirty).toBe(true); // 關頁面時仍會送
    fail = false;
    await vi.advanceTimersByTimeAsync(SAVE_RETRY_MS + 1);
    expect(sent).toEqual([1, 1]);
    expect(q.snapshot()).toEqual({ pending: null, retries: [] });

    // 退避期間同一張又改了：新的取代重試
    fail = true;
    q.schedule({ path: 'A', req: req(5) });
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS + 1);
    fail = false;
    q.schedule({ path: 'A', req: req(6) });
    await vi.advanceTimersByTimeAsync(SAVE_RETRY_MS + AUTOSAVE_MS + 1);
    expect(sent.slice(2)).toEqual([5, 6]);
    vi.useRealTimers();
  });

  test('unload sends the pending state and every save still in its back-off, with keepalive', async () => {
    vi.useFakeTimers();
    const sent: Array<[string, boolean]> = [];
    let fail = true;
    const q = new AutosaveQueue({
      send: async (job, keepalive) => {
        sent.push([job.path, keepalive]);
        if (fail) throw new Error('x');
        return { edit: null };
      },
      onSaved: () => {},
      onError: () => {},
    });
    q.schedule({ path: 'A', req: req(1) });
    await vi.advanceTimersByTimeAsync(AUTOSAVE_MS + 1); // A 失敗、進入退避
    fail = false;
    q.schedule({ path: 'B', req: req(2) });
    q.unload();
    await vi.advanceTimersByTimeAsync(0);
    expect(sent).toEqual([
      ['A', false],
      ['A', true],
      ['B', true],
    ]);
    vi.useRealTimers();
  });
});
