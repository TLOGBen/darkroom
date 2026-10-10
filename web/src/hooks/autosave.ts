/**
 * 照片庫的自動存檔佇列（PL15／PLP9、S1、S13 g／g'／g''、seal F3）。沒有 React、沒有 DOM，可以單獨測試。
 *
 * 規則（跟舊 app.js 一模一樣，只是搬成一個類別）：
 *   - 開著的照片每改一次，`schedule(job)` 記下「最新的一份」；AUTOSAVE_MS 後送出（只送最新的，舊的被覆蓋、不排隊）。
 *   - 送什麼（路徑與內容）在排程當下就固定（S1），不會之後才從畫面讀，所以換照片不會把 A 的狀態存到 B。
 *   - 送出失敗：toast 原因，退避 SAVE_RETRY_MS 後重試一次（S13 g）；重試前若同一張又有新的改變，新的取代它（g'）。
 *   - `flush()`：送出排隊中的那份並等到沒有東西在路上；`flushRetries()`：連退避中的失敗存檔也一起送（g''）。
 *     開另一張照片、貼上、匯出、存成 preset 之前都先呼叫，保證不會有舊的存檔晚到、蓋掉之後的動作。
 *   - `unload()`：頁面要關了，排隊的與退避中的全部立刻用 keepalive 送出（F3）。
 */
import { AUTOSAVE_MS, SAVE_RETRY_MS, retryDue, unloadJobs, type EditInfo } from '../domain/library';
import type { EditRequest } from '../domain/edit';

export interface SaveJob {
  path: string;
  req: EditRequest;
  retried?: boolean;
}

export interface AutosaveDeps {
  /** 把一份存檔送出去，回照片庫的最新狀態（PUT 的回應，或 paste 之後再 GET 一次）。 */
  send: (job: SaveJob, keepalive: boolean) => Promise<EditInfo>;
  /** 存檔成功：照片庫回來的狀態（呼叫端判斷是不是目前這張）。 */
  onSaved: (path: string, info: EditInfo) => void;
  /** 存檔失敗：後端原句。 */
  onError: (message: string) => void;
  /** 計時器（測試可以換掉）。 */
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (h: unknown) => void;
}

export class AutosaveQueue {
  private timer: unknown = null;
  private pending: SaveJob | null = null;
  private inflight: Promise<void> | null = null;
  private readonly retries = new Map<string, SaveJob>();
  /** 有沒有還沒送到的東西（beforeunload 用） */
  dirty = false;
  private readonly deps: Required<AutosaveDeps>;

  constructor(deps: AutosaveDeps) {
    this.deps = {
      setTimer: (fn, ms) => setTimeout(fn, ms),
      clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
      ...deps,
    };
  }

  /** 排一份存檔：同一張照片更新的狀態取代它還在退避的失敗存檔。 */
  schedule(job: SaveJob): void {
    this.pending = { ...job, retried: false };
    this.retries.delete(job.path);
    this.dirty = true;
    this.deps.clearTimer(this.timer);
    this.timer = this.deps.setTimer(() => void this.flush(), AUTOSAVE_MS);
  }

  private async sendOne(job: SaveJob, keepalive: boolean): Promise<void> {
    try {
      const info = await this.deps.send(job, keepalive);
      this.deps.onSaved(job.path, info);
    } catch (e) {
      this.deps.onError(e instanceof Error ? e.message : String(e));
      if (!job.retried) {
        // 立刻標成 dirty：退避期間關頁面，beforeunload 仍會送這份（但跟 pending 分開放，正在 flush 的迴圈不會提早重送）
        this.retries.set(job.path, { ...job, retried: true });
        this.dirty = true;
        this.deps.setTimer(() => void this.flushRetry(job.path), SAVE_RETRY_MS);
      }
    }
  }

  /** 送出排隊中的，並等到沒有東西在路上。 */
  async flush(): Promise<void> {
    this.deps.clearTimer(this.timer);
    this.timer = null;
    while (this.pending || this.inflight) {
      if (this.inflight) {
        await this.inflight;
        continue;
      }
      const job = this.pending as SaveJob;
      this.pending = null;
      this.dirty = this.retries.size > 0; // 失敗存檔還在等重試：關頁面時要送
      this.inflight = this.sendOne(job, false).finally(() => {
        this.inflight = null;
      });
    }
  }

  /** S13g'：一個失敗存檔的那一次重試（退避後，或現在）。 */
  async flushRetry(path: string): Promise<void> {
    const r = this.retries.get(path);
    if (!r) return;
    const due = retryDue(this.pending && this.pending.path, path);
    if (due === 'superseded') {
      this.retries.delete(path);
      return;
    }
    if (due === 'after') await this.flush(); // 別張排隊中的先送
    if (this.retries.get(path) !== r) return; // 期間被取代（或已送）
    this.retries.delete(path);
    if (this.pending && this.pending.path === path) return;
    this.pending = r;
    await this.flush();
  }

  /** 開另一張照片之前：失敗存檔一個都不留。 */
  async flushRetries(): Promise<void> {
    for (const path of [...this.retries.keys()]) await this.flushRetry(path);
    await this.flush(); // 別的呼叫端拿走的重試可能還在路上：等它
  }

  /** 頁面要關了：最新的與退避中的全部立刻送出（keepalive）。 */
  unload(): void {
    const jobs = unloadJobs(this.pending, [...this.retries.values()]);
    this.pending = null;
    this.retries.clear();
    this.dirty = false;
    for (const job of jobs) void this.sendOne(job, true);
  }

  /** 測試用：目前排隊與退避中的路徑。 */
  snapshot(): { pending: string | null; retries: string[] } {
    return { pending: this.pending?.path ?? null, retries: [...this.retries.keys()] };
  }
}
