// darkroom front-end logic without DOM access (shared by the page and the node:test suite).
// Contract R3 (slider semantics), R5 (undo history), R6 (tree keyboard, search, typed values, curves),
// CONTRACT-export X13 (export request and messages), CONTRACT-preset-library K19, CONTRACT-photo-library PL15 / PLP9.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.DarkroomLogic = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const clamp = (s, v) => Math.min(s.max, Math.max(s.min, v));
  const round = (v, d) => { const k = Math.pow(10, d); return Math.round(v * k) / k; };

  // ---------------------------------------------------------------- R3 slider semantics
  // raw = preset value at strength (hue angles are not scaled); base = clamp(raw);
  // shown value = clamp(base + tweak); a tweak is measured from base, i.e. from what the screen shows.
  function sliderView(s, presetValue, strengthPct, tweak) {
    const raw = s.hue ? presetValue : s.default + (strengthPct / 100) * (presetValue - s.default);
    const base = clamp(s, raw);
    const clamped = raw < s.min ? 'min' : (raw > s.max ? 'max' : null);
    return {raw, base, value: clamp(s, base + (tweak || 0)), clamped, tweak: tweak || 0};
  }

  function tweakFor(s, presetValue, strengthPct, value) {
    const d = clamp(s, value) - sliderView(s, presetValue, strengthPct, 0).base;
    return Math.abs(d) < s.step / 2 ? 0 : round(d, 6);
  }

  function fmtNum(s, v) {
    if (s.step < 1) return (v > 0 && s.min < 0 ? '+' : '') + v.toFixed(2);
    const r = Math.round(v);
    return (r > 0 && s.min < 0 ? '+' : '') + r;
  }

  function fmtRaw(v) { return String(round(v, 2)); }

  function clampNote(view) {
    return view.clamped ? `（原 ${fmtRaw(view.raw)}）` : '';
  }

  function sliderTooltip(s, presetValue, strengthPct, tweak) {
    const v = sliderView(s, presetValue, strengthPct, tweak);
    let t = `preset × ${strengthPct}% = ${fmtRaw(v.raw)}`;
    if (v.clamped) t += `，已到${v.clamped === 'min' ? '下限' : '上限'} ${fmtRaw(v.clamped === 'min' ? s.min : s.max)}`;
    if (v.tweak) t += `；微調 ${v.tweak > 0 ? '+' : ''}${fmtRaw(v.tweak)}`;
    return t + '；雙擊＝還原這一項';
  }

  // ---------------------------------------------------------------- R5 undo history
  const copy = (state) => JSON.parse(JSON.stringify(state));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  class History {
    constructor(limit) { this.limit = limit || 200; this.past = []; this.future = []; }
    push(state) {                       // record the state before a change
      const s = copy(state);
      if (!this.past.length || !same(this.past[this.past.length - 1], s)) {
        this.past.push(s);
        if (this.past.length > this.limit) this.past.shift();
      }
      this.future = [];
    }
    undo(current) {
      if (!this.past.length) return null;
      this.future.push(copy(current));
      return this.past.pop();
    }
    redo(current) {
      if (!this.future.length) return null;
      this.past.push(copy(current));
      return this.future.pop();
    }
    canUndo() { return this.past.length > 0; }
    canRedo() { return this.future.length > 0; }
  }

  // ---------------------------------------------------------------- R5 editor state (reducer)
  // ed = {presetId, strength, tweaks, geometry, past: [snapshot], future: [snapshot], gesture: string|null}
  // A snapshot is {presetId, strength, tweaks, geometry} (S3 C24: the crop / rotation is one more part of it).
  // Every change records the state before it, except further steps of the same gesture (one drag = one step).
  // Changes that change nothing record nothing.
  const HISTORY_LIMIT = 200;
  const snap = (ed) => ({presetId: ed.presetId, strength: ed.strength, tweaks: Object.assign({}, ed.tweaks),
                         geometry: ed.geometry ? JSON.parse(JSON.stringify(ed.geometry)) : null});

  function initialEditor() {
    return {presetId: null, strength: 100, tweaks: {}, geometry: null, past: [], future: [], gesture: null};
  }

  const strengthEnabled = (ed) => ed.presetId !== null;
  const strengthInEffect = (ed) => (ed.presetId === null ? 100 : ed.strength);
  const canUndo = (ed) => ed.past.length > 0;
  const canRedo = (ed) => ed.future.length > 0;
  // S11: the hint only while the state is carried over (no edit of this photo yet); a saved edit needs no hint
  const carryHintVisible = (ed, hasImage, hasEdit) =>
    !!hasImage && !hasEdit && (ed.presetId !== null || Object.keys(ed.tweaks).length > 0);

  function change(ed, next, gesture) {
    const now = snap(ed);
    if (same(now, snap(Object.assign({}, ed, next)))) {
      // nothing changed: a gesture only counts as started once it has changed something
      const keep = gesture && ed.gesture === gesture ? gesture : null;
      return keep === ed.gesture ? ed : Object.assign({}, ed, {gesture: keep});
    }
    const continuing = gesture && ed.gesture === gesture;
    const past = continuing ? ed.past : ed.past.concat([now]).slice(-HISTORY_LIMIT);
    return Object.assign({}, ed, next, {past, future: [], gesture: gesture || null});
  }

  function reduce(ed, a) {
    switch (a.type) {
      case 'selectPreset':              // strength and tweaks are kept
        return change(ed, {presetId: a.id === undefined ? null : a.id});
      case 'setStrength': {
        if (!strengthEnabled(ed)) return ed;
        const v = Math.min(200, Math.max(0, Math.round(a.value)));
        return change(ed, {strength: v}, a.gesture);
      }
      case 'setValue': {
        const d = tweakFor(a.slider, a.presetValue, strengthInEffect(ed), a.value);
        const tweaks = Object.assign({}, ed.tweaks);
        if (d) tweaks[a.slider.key] = d; else delete tweaks[a.slider.key];
        return change(ed, {tweaks}, a.gesture);
      }
      case 'resetKey': {
        if (!(a.key in ed.tweaks)) return ed;
        const tweaks = Object.assign({}, ed.tweaks);
        delete tweaks[a.key];
        return change(ed, {tweaks});
      }
      case 'resetAll':
        return Object.keys(ed.tweaks).length ? change(ed, {tweaks: {}}) : ed;
      case 'resetToOriginal':           // S10 / S10': no preset, no tweaks, no geometry; one step (strength kept)
        return change(ed, {presetId: null, tweaks: {}, geometry: null});
      case 'setGeometry':               // S3 C22 / C24: the crop mode's result, or a rotate / flip outside it: one step
        return change(ed, {geometry: normGeometry(a.geometry)});
      case 'carry': {                   // C24: another photo opened - its crop is its own, never carried over
        const g = carryGeometry();
        const drop = (list) => list.map((x) => Object.assign({}, x, {geometry: g}));
        return Object.assign({}, ed, {geometry: g, past: drop(ed.past), future: drop(ed.future), gesture: null});
      }
      case 'endGesture':
        return ed.gesture ? Object.assign({}, ed, {gesture: null}) : ed;
      case 'restoreEdit': {             // PL15 / PLP9: a photo's saved edit comes back; history starts afresh
        const e = a.edit;
        return {presetId: e.preset ? e.preset.id : null, strength: e.strength, tweaks: Object.assign({}, e.overrides),
                geometry: normGeometry(e.geometry === undefined ? null : e.geometry), past: [], future: [], gesture: null};
      }
      case 'undo': {
        if (!canUndo(ed)) return ed;
        const prev = ed.past[ed.past.length - 1];
        return Object.assign({}, ed, copy(prev), {past: ed.past.slice(0, -1), future: ed.future.concat([snap(ed)]),
                                                   gesture: null});
      }
      case 'redo': {
        if (!canRedo(ed)) return ed;
        const next = ed.future[ed.future.length - 1];
        return Object.assign({}, ed, copy(next), {past: ed.past.concat([snap(ed)]), future: ed.future.slice(0, -1),
                                                   gesture: null});
      }
      default:
        throw new Error('unknown action ' + a.type);
    }
  }

  // ---------------------------------------------------------------- R6 tree keyboard
  // rows: visible rows in order, {type: 'folder'|'preset', depth, open, parent: index or -1}
  function treeKey(rows, i, key) {
    const n = rows.length, row = rows[i];
    if (!row) return null;
    const at = (focus, action) => ({focus, action: action || null});
    switch (key) {
      case 'ArrowDown': return at(Math.min(i + 1, n - 1));
      case 'ArrowUp': return at(Math.max(i - 1, 0));
      case 'Home': return at(0);
      case 'End': return at(n - 1);
      case 'Enter': return at(i, row.type === 'preset' ? 'apply' : 'toggle');
      case 'ArrowRight':
        if (row.type !== 'folder') return at(i);
        if (!row.open) return at(i, 'expand');
        return at(i + 1 < n && rows[i + 1].depth > row.depth ? i + 1 : i);
      case 'ArrowLeft':
        if (row.type === 'folder' && row.open) return at(i, 'collapse');
        return at(row.parent >= 0 ? row.parent : i);
      default: return null;
    }
  }

  // ---------------------------------------------------------------- R6 search
  // R6 + CONTRACT-semantic-index SI10: name, group and the semantic tags (zh + en) are searched
  function matchPreset(p, query) {
    const terms = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
    const hay = (p.name + ' ' + (p.group || '') + ' ' + (p.tags || []).join(' ')).toLowerCase();
    return terms.every((t) => hay.includes(t));
  }

  // SI10: the row's tooltip - "{group} / {name}｜{tags joined by 、}"
  function presetTitle(p) {
    const base = p.group ? p.group + ' / ' + p.name : p.name;
    return p.tags && p.tags.length ? base + '｜' + p.tags.join('、') : base;
  }

  // ---------------------------------------------------------------- R6 typed values
  function parseValueInput(text, s) {
    const t = String(text || '').trim().replace(/[−–]/g, '-').replace(/[%％]$/, '').replace(/^\+/, '');
    if (!/^-?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
    return clamp(s, parseFloat(t));
  }

  // ---------------------------------------------------------------- R6 curves
  function curveAtStrength(points, strengthPct) {
    const k = strengthPct / 100;
    return points.map(([x, y]) => [x, Math.min(255, Math.max(0, round(x + k * (y - x), 6)))]);
  }

  function curvePath(points, size) {
    const pts = [...points].sort((a, b) => a[0] - b[0]);
    if (!pts.length) return '';
    const f = (v) => (v / 255 * size).toFixed(1);
    const g = (v) => ((1 - v / 255) * size).toFixed(1);
    const all = pts[0][0] > 0 ? [[0, pts[0][1]], ...pts] : pts;
    const last = all[all.length - 1];
    if (last[0] < 255) all.push([255, last[1]]);
    return all.map(([x, y], i) => (i ? 'L' : 'M') + f(x) + ' ' + g(y)).join(' ');
  }

  // ---------------------------------------------------------------- X13 export
  // The export reads the current edit (never changes it); over HTTP there is no dest_dir (XP16).
  const EXPORT_BUSY = '匯出中…';
  const EXPORT_DEFAULT_QUALITY = 92;
  const baseName = (p) => String(p || '').split(/[\\/]/).pop();
  const exportDone = (outputPath) => `已匯出：${outputPath}`;
  const exportFailed = (fileName, reason) => `匯出失敗：${fileName}：${reason}`;

  function exportBody(req, format, qualityText) {
    const body = {items: [{image_id: req.image_id, preset_id: req.preset_id, strength: req.strength,
                           overrides: req.overrides}], format};
    if (format === 'jpeg') {
      const t = String(qualityText == null ? '' : qualityText).trim();
      body.quality = t === '' ? EXPORT_DEFAULT_QUALITY : (/^\d+$/.test(t) ? parseInt(t, 10) : t);   // the server judges
    }
    return body;
  }

  function exportMessage(result) {        // one entry of results: {ok, source, output} | {ok: false, source, error}
    return result.ok ? exportDone(result.output) : result.error;
  }

  // ---------------------------------------------------------------- K19 preset library
  // Favorites, the action menus, import (uploaded bytes only: no path goes over HTTP, KP4) and "save as preset".
  // Saving reads the edit and never changes it (no dispatch, no undo step).
  const USER_GROUP = '自存 preset';
  const FAV_EMPTY = '還沒有最愛，按 preset 旁的 ☆ 加入';
  const UPLOAD_BATCH_CHARS = 700000;                        // KP4: base64 per request, under the 1 MiB body limit
  const presetSaved = (name) => `已存成 preset：${name}`;
  const importSummary = (ok, fail) => `已匯入 ${ok} 個，${fail} 個沒有匯入`;
  const importedLine = (id) => `已匯入：${id}`;
  const groupCreated = (group) => `已建立群組：${group}`;
  const canSavePreset = (ed) => ed.presetId !== null || Object.keys(ed.tweaks).some((k) => ed.tweaks[k]);
  const favMark = (fav) => (fav ? '★' : '☆');

  function saveBody(req, name, group) {      // req = the preview request of the current edit
    const body = {name, group: group || USER_GROUP, preset_id: req.preset_id, strength: req.strength,
                  overrides: req.overrides};
    return body;
  }

  function uploadBatches(files) {            // files: [{name, data_base64}] -> batches of at most UPLOAD_BATCH_CHARS
    const out = [];
    let cur = [], size = 0;
    for (const f of files) {
      const n = f.data_base64.length + f.name.length;
      if (cur.length && size + n > UPLOAD_BATCH_CHARS) { out.push(cur); cur = []; size = 0; }
      cur.push(f); size += n;
    }
    if (cur.length) out.push(cur);
    return out;
  }

  function importReport(results) {           // {summary, lines}: one line per file, in order
    const ok = results.filter((r) => r.ok).length;
    return {summary: importSummary(ok, results.length - ok),
            lines: results.map((r) => (r.ok ? importedLine(r.id) : r.error))};
  }

  // ---------------------------------------------------------------- S14 English service sentences, explained
  // The services' sentences (CONTRACT-layering L3, photo library constants) are never changed; the page shows
  // the Chinese explanation and keeps the original in the tooltip. Exact sentences first, then prefix forms.
  const EXPLAIN_EXACT = {
    'path is required': '請輸入照片路徑',
    'unsupported photo format (JPEG/PNG/TIFF/HEIC)': '不支援的照片格式（只接受 JPEG／PNG／TIFF／HEIC）',
    'unknown image_id': '照片已不在記憶體裡，請重新開啟',
    'strength must be a number in 0..200': '強度要在 0～200 之間',
    'body must be JSON': '請求格式錯誤（不是 JSON）',
  };
  const EXPLAIN_PREFIX = [
    ['photo not found: ', (x) => `找不到照片：${x}`],
    ['unknown or unsupported preset ', (x) => `找不到或不支援的 preset：${x}`],
    ['unknown preset ', (x) => `找不到 preset：${x}`],
    ['strength must be within 0..200, got ', (x) => `強度要在 0～200 之間：${x}`],
    ['unknown slider key ', (x) => `未知的滑桿：${x}`],
    ['request refused: ', (x) => `伺服器拒絕了這個請求：${x}`],
  ];
  function explainOne(m) {               // one service sentence, whole -> Chinese, or null
    if (Object.prototype.hasOwnProperty.call(EXPLAIN_EXACT, m)) return EXPLAIN_EXACT[m];
    for (const [prefix, fn] of EXPLAIN_PREFIX) if (m.startsWith(prefix)) return fn(m.slice(prefix.length));
    return null;
  }
  // S14: the whole message, or - for the page's own composite sentences ("匯出失敗：{file}：{reason}",
  // "預覽失敗：{reason}") - the service sentence after a full-width colon; everything else unchanged
  function explain(msg) {
    const m = String(msg == null ? '' : msg);
    const whole = explainOne(m);
    if (whole !== null) return whole;
    for (let i = m.indexOf('：'); i >= 0; i = m.indexOf('：', i + 1)) {
      const tail = explainOne(m.slice(i + 1));
      if (tail !== null) return m.slice(0, i + 1) + tail;
    }
    return m;
  }

  // ---------------------------------------------------------------- PL15 / PLP9 photo library
  // The edit of the open photo is saved AUTOSAVE_MS after the last change (latest wins); restoring a saved edit
  // goes through the reducer's restoreEdit and never schedules a save. The grid selects, copies, pastes, exports.
  const AUTOSAVE_MS = 500;
  const SAVE_RETRY_MS = 2000;                                // S13 (g): one retry after a failed save
  // S13g': a failed save's retry, given the path of what is pending now: a newer change of the same photo
  // supersedes it; another photo's pending save goes first; nothing pending -> now
  const retryDue = (pendingPath, retryPath) =>
    (pendingPath == null ? 'now' : pendingPath === retryPath ? 'superseded' : 'after');
  // what beforeunload sends: every failed save still in its back-off (unless the same photo has a newer
  // pending state), then the pending one - nothing is left behind when the page goes away
  const unloadJobs = (pending, retries) =>
    [...retries.filter((r) => !pending || r.path !== pending.path), ...(pending ? [pending] : [])];
  const CARRY_HINT = '沿用上一張的設定（還不是這張的編輯，會再沿用到下一張）';   // S11 (replaces R5's sentence)
  const CARRY_HINT_SHORT = '沿用中';
  const openFailed = (fileName, reason) => `開啟失敗：${fileName}：${reason}`;
  const GRID_EMPTY = '這個資料夾沒有支援的照片（JPEG／PNG／TIFF／HEIC）';   // S13 (j)

  // ---------------------------------------------------------------- S17 drawn sliders: CSS variables, hue dots, canvas
  // --base = where the preset puts the value, --lo..--hi = from there to the thumb (your tweak); 0..100 % of the range.
  const pct = (s, v) => Math.max(0, Math.min(100, (clamp(s, v) - s.min) / (s.max - s.min) * 100));
  function sliderVars(s, view) {
    const a = pct(s, view.base), b = pct(s, view.value);
    return {base: a.toFixed(2) + '%', lo: Math.min(a, b).toFixed(2) + '%', hi: Math.max(a, b).toFixed(2) + '%'};
  }
  function strengthVars(strength) {      // the dial: 0..200, 100 is the centre
    const a = 50, b = Math.max(0, Math.min(100, strength / 2));
    return {base: '50%', lo: Math.min(a, b).toFixed(2) + '%', hi: Math.max(a, b).toFixed(2) + '%'};
  }
  const bipolar = (s) => s.min < 0 && s.max > 0;
  const HUE_DOTS = {Red: '#e04848', Orange: '#e08a3c', Yellow: '#d9c43a', Green: '#4fb24f', Aqua: '#3fb8a8', Blue: '#4a7fe0',
                    Purple: '#8c5fd6', Magenta: '#d65aa8'};
  function hueDot(key) {                 // HSL rows: a 6 px dot of the colour the row is about (never on the track)
    const m = /^(?:Hue|Saturation|Luminance)Adjustment(\w+)$/.exec(key);
    return m && HUE_DOTS[m[1]] ? HUE_DOTS[m[1]] : null;
  }
  const CANVASES = ['dark', 'black', 'mid'];
  const CANVAS_STORAGE_KEY = 'darkroom.canvas';
  const canvasFrom = (stored) => (CANVASES.includes(stored) ? stored : 'dark');

  // ---------------------------------------------------------------- S7 A/B compare: the split (never in the reducer)
  const AB_KEY = 'y';
  const AB_STORAGE_KEY = 'darkroom.abSplit';
  const AB_DEFAULT_SPLIT = 0.5;
  const clamp01 = (v) => Math.min(1, Math.max(0, v));
  function abStep(split, key, shift) {    // keyboard on the handle: null when the key is not ours
    const step = shift ? 0.1 : 0.01;
    switch (key) {
      case 'ArrowLeft': return clamp01(split - step);
      case 'ArrowRight': return clamp01(split + step);
      case 'Home': return 0;
      case 'End': return 1;
      default: return null;
    }
  }
  function abSplitFrom(stored) {          // sessionStorage -> 0..1, else the default
    const v = parseFloat(stored);
    return Number.isFinite(v) && v >= 0 && v <= 1 ? v : AB_DEFAULT_SPLIT;
  }

  // ---------------------------------------------------------------- S8 / S9 / S10 grid badges, filter, reset / restore
  const FILTERS = ['all', 'edited', 'plain'];
  const FILTER_LABELS = {all: '全部', edited: '已編輯', plain: '未編輯'};
  const BADGE_ONLY_TWEAKS = '只有微調';
  const BADGE_CHANGED = '（preset 已變更）';
  const BADGE_MISSING = '（preset 已不在庫裡）';
  function badgeTitle(info) {             // info: X-Edit {preset, strength, status, geometry, tweaks}; null = no detail
    if (!info) return '已編輯';
    // S8b (CONTRACT-s3-crop C18): the strength only with a preset; a geometry with colours adds 「・已裁切」
    let t = info.preset ? `${info.preset}　${info.strength}%` : info.geometry && !info.tweaks ? BADGE_ONLY_GEOMETRY
      : BADGE_ONLY_TWEAKS;
    if (info.geometry && (info.preset || info.tweaks)) t += BADGE_CROPPED;
    return t + (info.status === 'changed' ? BADGE_CHANGED : info.status === 'missing' ? BADGE_MISSING : '');
  }
  const stale = (info) => !!info && (info.status === 'changed' || info.status === 'missing');
  function gridFilter(items, filter) {    // {shown: [[index, item]], pending: n}: null edited only under "all"
    const shown = [], unknown = items.filter((it) => it.edited === null || it.edited === undefined).length;
    items.forEach((it, i) => {
      if (filter === 'edited' ? it.edited === true : filter === 'plain' ? it.edited === false : true) shown.push([i, it]);
    });
    return {shown, pending: filter === 'all' ? 0 : unknown};
  }
  // S9: under a filter only the cells shown can be selected - a Shift range never reaches a hidden photo
  const onlyShown = (sel, shown) => (shown ? new Set([...sel].filter((i) => shown.has(i))) : new Set(sel));
  const gridPending = (k) => `還有 ${k} 張尚未判定`;
  const resetConfirm = (n) => `要把 ${n} 張照片還原成原圖嗎？（可用「取回上一份」拿回來）`;
  const resetDone = (ok, failed) => `已還原 ${ok} 張，失敗 ${failed} 張`;
  const restoreDone = (ok, failed) => `已取回 ${ok} 張，失敗 ${failed} 張`;
  const RESET_TOAST = '已還原成原圖（Ctrl+Z 可拿回）';
  const RESTORE_TOAST = '已取回上一份編輯';
  const PRESET_CHANGED = 'preset 已變更，這份編輯用的是當時的 preset 快照';
  const PRESET_MISSING = 'preset 已不在庫裡，這份編輯用的是當時的 preset 快照';
  const presetStatusText = (status) => (status === 'changed' ? PRESET_CHANGED : status === 'missing' ? PRESET_MISSING : '');
  const copied = (sourceName) => `已複製 ${sourceName} 的編輯`;
  const pasteConfirm = (sourceName, n) => `要用 ${sourceName} 的編輯取代 ${n} 張照片的編輯嗎？`;
  const pasteDone = (ok, failed) => `已貼上 ${ok} 張，失敗 ${failed} 張`;
  const exportSelectedDone = (ok, failed) => `已匯出 ${ok} 張，失敗 ${failed} 張`;
  const gridCount = (n, total) => `已選 ${n}／${total} 張`;
  const saveEditFailed = (reason) => `儲存編輯失敗：${reason}`;
  const loadEditFailed = (reason) => `讀取編輯失敗：${reason}`;
  // S3 seal (CONTRACT-s3-crop C29): a photo whose saved edit could not be read is never saved over - the screen
  // state is not that edit, so an autosave would replace the saved crop and colours with it
  const EDIT_UNREADABLE = '讀不到已存的編輯：這張的修改先不會自動存檔（以免蓋掉原本存的裁切與顏色），請重新開啟這張照片';
  const saveAllowed = (unreadablePath, path) => unreadablePath == null || unreadablePath !== path;
  const loadFolderFailed = (reason) => `讀取資料夾失敗：${reason}`;

  function editBody(ed, path) {         // PUT /api/edit: the open photo's edit as the editor shows it
    const overrides = {};
    for (const [k, d] of Object.entries(ed.tweaks)) if (d) overrides[k] = d;
    // C24: the geometry always goes with it (null too: "none", never "keep what is saved")
    return {path, preset_id: ed.presetId, strength: strengthInEffect(ed), overrides, geometry: normGeometry(ed.geometry)};
  }

  // S2 (CONTRACT-s1-experience): the autosave request for the state `ed` of the photo at `path`. When the page
  // remembers a snapshot for the chosen preset (from GET / PUT /api/edit of this photo), the edit is written
  // through paste with that snapshot (PL8: never re-read from the library), else through PUT (PL4).
  function editRequest(ed, path, snapshots, fingerprint) {
    const body = editBody(ed, path);
    const snap = ed.presetId !== null && snapshots ? snapshots[ed.presetId] : null;
    if (!snap) return {method: 'PUT', body};
    const edit = {schema: body.geometry ? 'darkroom-edit/2' : 'darkroom-edit/1', fingerprint: fingerprint || '',
                  preset: snap, strength: body.strength, overrides: body.overrides};
    if (body.geometry) edit.geometry = body.geometry;               // C12: /2 only with a geometry
    // S2b (CONTRACT-s3-crop C14): the page's own save carries its geometry - a paste keeps the target's geometry
    // unless with_geometry, and that would drop the box just cropped
    return {method: 'PASTE', body: {targets: [path], edit, with_geometry: true}};
  }

  // S3: slider base values and curves come from the edit's snapshot, never from the library's current file;
  // banner / note (the skipped settings) still come from the library detail when the preset is still there.
  function detailFromSnapshot(snapshot, detail) {
    const p = snapshot.params || {};
    return {id: snapshot.id, name: snapshot.name, group: snapshot.group,
            values: Object.assign({}, p.values || {}), curves: Object.assign({}, p.curves || {}),
            banner: detail ? detail.banner : '', note: detail ? detail.note : '', snapshot: true};
  }

  function gridSelect(sel, i, mods, anchor) {   // click = only i; Ctrl = toggle i; Shift = anchor..i
    const out = new Set(mods && mods.ctrl ? sel : []);
    if (mods && mods.shift) {
      const a = anchor == null ? 0 : anchor;
      for (let k = Math.min(a, i); k <= Math.max(a, i); k++) out.add(k);
      return {sel: out, anchor: a};
    }
    if (mods && mods.ctrl) { if (out.has(i)) out.delete(i); else out.add(i); return {sel: out, anchor: i}; }
    out.add(i);
    return {sel: out, anchor: i};
  }

  function exportItems(paths, edits) {  // edits: {path: get_edit result | null (failed)} -> {items, failed}
    const items = [];
    let failed = 0;
    for (const p of paths) {
      const r = edits[p];
      if (!r) { failed++; continue; }
      if (r.edit) items.push({path: p, preset_id: r.edit.preset ? r.edit.preset.id : null, strength: r.edit.strength,
                              overrides: r.edit.overrides});
      else items.push({path: p});
    }
    return {items, failed};
  }

  // ---------------------------------------------------------------- S2 export dialog (CONTRACT-s2-export-detect E1, E8, E29)
  // The server's normalize_settings is the one rule; these helpers only mirror it for what the dialog shows and
  // disables. A value the user typed that is not a number goes to the server as typed (the server says why).
  const EXPORT_SETTINGS_KEY = 'darkroom.exportSettings';
  const EXPORT_FORMATS = ['jpeg', 'png', 'tiff', 'webp'];
  const FORMAT_LABELS = {jpeg: 'JPEG', png: 'PNG', tiff: 'TIFF', webp: 'WebP'};
  const RESIZE_MODES = ['long_edge', 'short_edge', 'width', 'height', 'megapixels', 'percent'];
  const RESIZE_LABELS = {long_edge: '長邊', short_edge: '短邊', width: '寬', height: '高', megapixels: '百萬像素', percent: '百分比'};
  const METADATA_LABELS = {all: '全部中繼資料', copyright: '只留版權', none: '不含中繼資料'};
  const REMOVE_GPS_LABEL = '移除 GPS';
  const SHARPEN_TARGETS = ['screen', 'matte', 'glossy'];
  const SHARPEN_TARGET_LABELS = {screen: '螢幕', matte: '霧面紙', glossy: '光面紙'};
  const SHARPEN_AMOUNTS = ['low', 'standard', 'high'];
  const SHARPEN_AMOUNT_LABELS = {low: '低', standard: '標準', high: '高'};
  const NO_RESIZE_LABEL = '不縮放';
  const NO_SHARPEN_LABEL = '不銳利化';
  const ORIGINAL_SIZE = '原尺寸';
  const CUSTOM_PRESET = '（自訂）';
  const EXPORT_DEFAULTS = {format: 'jpeg', bit_depth: 8, quality: 92, max_kb: null, resize: null, metadata: 'all',
                           remove_gps: false, sharpen: null};
  const defaultBitDepth = (format) => (format === 'tiff' ? 16 : 8);
  const lossy = (format) => format === 'jpeg' || format === 'webp';
  const exportPresetSaved = (name) => `已存成匯出預設：${name}`;
  const exportPresetUpdated = (name) => `已更新匯出預設：${name}`;
  const exportPresetDeleted = (name) => `已刪除匯出預設：${name}`;
  const UNDO_LABEL = '復原';
  const EXPORT_PRESET_NAME_PROMPT = '匯出預設的名稱（1～60 個字；同名會取代，可復原）';

  // E8 mirror: the size the server writes (only ever smaller), from the upright size and the resize setting
  function resizeTarget(w, h, resize) {
    if (!resize) return [w, h];
    const m = resize.mode, v = resize.value;
    const s = {long_edge: v / Math.max(w, h), short_edge: v / Math.min(w, h), width: v / w, height: v / h,
               megapixels: Math.sqrt(v * 1e6 / (w * h)), percent: v / 100}[m];
    if (s === undefined || !(s < 1)) return [w, h];
    const rnd = (x) => Math.max(1, Math.floor(x + 0.5));
    if (m === 'megapixels') return [Math.max(1, Math.floor(w * s)), Math.max(1, Math.floor(h * s))];
    if (m === 'percent') return [rnd(w * s), rnd(h * s)];
    if (m === 'width') return [v, rnd(h * s)];
    if (m === 'height') return [rnd(w * s), v];
    if (m === 'long_edge') return w >= h ? [v, rnd(h * s)] : [rnd(w * s), v];
    return w <= h ? [v, rnd(h * s)] : [rnd(w * s), v];          // short_edge
  }

  const numberOrText = (t) => {                     // the server judges anything that is not a plain number
    const s = String(t == null ? '' : t).trim();
    return /^-?(\d+\.?\d*|\.\d+)$/.test(s) ? Number(s) : s;
  };

  // the form's raw values -> the 8 settings keys the server takes (only the keys that apply to the format)
  function settingsFromForm(f) {
    const format = f.format;
    const resize = f.resize_mode ? {mode: f.resize_mode, value: numberOrText(f.resize_value)} : null;
    const sharpen = f.sharpen_target ? {target: f.sharpen_target, amount: f.sharpen_amount || 'standard'} : null;
    return {format,
            bit_depth: lossy(format) ? 8 : numberOrText(f.bit_depth || defaultBitDepth(format)),
            quality: lossy(format) ? numberOrText(f.quality === '' || f.quality == null ? EXPORT_DEFAULTS.quality : f.quality) : null,
            max_kb: format === 'jpeg' && f.max_kb_on ? numberOrText(f.max_kb) : null,
            resize, metadata: f.metadata || 'all', remove_gps: (f.metadata || 'all') === 'all' && !!f.remove_gps, sharpen};
  }

  // what localStorage (or an export preset) holds -> complete settings; anything unreadable falls back to the default
  function exportSettingsFrom(stored) {
    let o = stored;
    if (typeof stored === 'string') { try { o = JSON.parse(stored); } catch (e) { o = null; } }
    if (!o || typeof o !== 'object') return Object.assign({}, EXPORT_DEFAULTS);
    const format = EXPORT_FORMATS.includes(o.format) ? o.format : EXPORT_DEFAULTS.format;
    const okRes = o.resize && RESIZE_MODES.includes(o.resize.mode) && typeof o.resize.value === 'number';
    const okSh = o.sharpen && SHARPEN_TARGETS.includes(o.sharpen.target) && SHARPEN_AMOUNTS.includes(o.sharpen.amount);
    return {format,
            bit_depth: lossy(format) ? 8 : ([8, 16].includes(o.bit_depth) ? o.bit_depth : defaultBitDepth(format)),
            quality: lossy(format) ? (Number.isInteger(o.quality) && o.quality >= 1 && o.quality <= 100 ? o.quality : EXPORT_DEFAULTS.quality) : null,
            max_kb: format === 'jpeg' && Number.isInteger(o.max_kb) ? o.max_kb : null,
            resize: okRes ? {mode: o.resize.mode, value: o.resize.value} : null,
            metadata: Object.prototype.hasOwnProperty.call(METADATA_LABELS, o.metadata) ? o.metadata : 'all',
            remove_gps: o.remove_gps === true,
            sharpen: okSh ? {target: o.sharpen.target, amount: o.sharpen.amount} : null};
  }

  // E29: which controls are disabled, decided here only (caps: the features of GET /api/capabilities, or null)
  function exportDialogState(settings, caps) {
    const f = settings.format;
    const webp = caps && caps.webp && caps.webp.available === false ? caps.webp.reason || '' : null;
    const mode = settings.resize ? settings.resize.mode : '';
    const range = mode === 'megapixels' ? {min: 0.01, max: 1000, step: 0.01}
      : mode === 'percent' ? {min: 0.01, max: 100, step: 0.01} : {min: 1, max: 65535, step: 1};
    return {quality: {disabled: !lossy(f)},
            bitDepth: {disabled: lossy(f), options: lossy(f) ? [8] : [8, 16]},
            maxKbOn: {disabled: f !== 'jpeg'},
            maxKb: {disabled: f !== 'jpeg' || settings.max_kb == null},
            webp: {disabled: webp !== null, title: webp || ''},
            go: {disabled: f === 'webp' && webp !== null},
            resizeValue: Object.assign({disabled: !mode}, range),
            removeGps: {disabled: settings.metadata !== 'all'},
            sharpenAmount: {disabled: !settings.sharpen}};
  }

  // E29: one line, e.g. 「JPEG 品質 92 ・長邊 2048 px ・全部中繼資料 ・螢幕銳利化（標準）」
  function exportSummary(s) {
    const parts = [];
    const fl = FORMAT_LABELS[s.format] || String(s.format);
    parts.push(lossy(s.format) ? `${fl} 品質 ${s.quality == null ? EXPORT_DEFAULTS.quality : s.quality}`
      : `${fl} ${s.bit_depth == null ? defaultBitDepth(s.format) : s.bit_depth}-bit`);
    if (s.format === 'jpeg' && s.max_kb != null) parts.push(`最大 ${s.max_kb} KB`);
    if (!s.resize) parts.push(ORIGINAL_SIZE);
    else if (s.resize.mode === 'megapixels') parts.push(`${s.resize.value} 百萬像素`);
    else if (s.resize.mode === 'percent') parts.push(`${s.resize.value}%`);
    else parts.push(`${RESIZE_LABELS[s.resize.mode] || s.resize.mode} ${s.resize.value} px`);
    parts.push((METADATA_LABELS[s.metadata] || s.metadata) + (s.metadata === 'all' && s.remove_gps ? `（${REMOVE_GPS_LABEL}）` : ''));
    if (s.sharpen) parts.push(`${SHARPEN_TARGET_LABELS[s.sharpen.target] || s.sharpen.target}銳利化（${SHARPEN_AMOUNT_LABELS[s.sharpen.amount] || s.sharpen.amount}）`);
    return parts.join(' ・');
  }

  // two settings objects say the same thing (key order and missing-vs-null ignored)
  function sameSettings(a, b) {
    const canon = (v) => (v === undefined ? null : v !== null && typeof v === 'object'
      ? Object.keys(v).sort().map((k) => [k, canon(v[k])]) : v);
    const keys = Object.keys(EXPORT_DEFAULTS);
    return JSON.stringify(keys.map((k) => canon(a && a[k]))) === JSON.stringify(keys.map((k) => canon(b && b[k])));
  }

  // POST /api/export: the items and the 8 settings; never a folder over HTTP (XP16)
  const exportRequest = (items, settings) => Object.assign({items}, settings);

  // ---------------------------------------------------------------- S2 capabilities (E22, E23, E30)
  const CAP_ORDER = ['gpu', 'heic', 'webp', 'photo_library', 'preset_library_writes', 'semantic_index', 'onepassword'];
  const CAP_LABELS = {gpu: '顯示卡（GPU）', heic: 'HEIC 照片', webp: 'WebP 匯出', photo_library: '照片庫（自動存編輯）',
                      preset_library_writes: '整理 preset 庫', semantic_index: 'preset 語意索引', onepassword: '1Password 登入'};
  const CAP_OK = '功能正常';
  const CAP_AVAILABLE = '可用';
  const CAP_REFRESH = '重新偵測';
  const capStatus = (n) => `功能狀態：${n} 項關閉`;
  const capOff = (features) => CAP_ORDER.filter((k) => features && features[k] && features[k].available === false);
  const capButtonText = (features) => { const n = capOff(features).length; return n ? capStatus(n) : CAP_OK; };
  const capLine = (key, f) => `${CAP_LABELS[key] || key}：${f && f.available ? CAP_AVAILABLE : '關閉：' + ((f && f.reason) || '')}`;
  // the reason a feature is off, or null (unknown features count as on: the page never blocks on a missing answer)
  const capReason = (features, key) => (features && features[key] && features[key].available === false ? features[key].reason || '' : null);

  // ---------------------------------------------------------------- S2 preset download (E16, E30)
  const DOWNLOAD_XMP = '下載 .xmp';
  const DOWNLOAD_GROUP_XMP = '下載整個群組的 .xmp';
  const PRESET_IDS_MAX = 500;                                 // E16: one request takes 1..500 ids; more go in batches
  const downloadSummary = (ok, fail) => `已下載 ${ok} 個 .xmp，${fail} 個沒有下載`;
  const downloadedLine = (fileName) => `已下載：${fileName}`;
  const downloadTooMany = (n) => `這個群組有 ${n} 個 preset，一次最多下載 500 個；請先下載裡面的子群組`;   // E30 (seal F4)
  function idBatches(ids) {
    const out = [];
    for (let i = 0; i < ids.length; i += PRESET_IDS_MAX) out.push(ids.slice(i, i + PRESET_IDS_MAX));
    return out;
  }
  function groupPresetIds(presets, path) {   // the group and every sub-group under it (" - " levels)
    return presets.filter((p) => { const g = (p.group || '').trim(); return g === path || g.startsWith(path + ' - '); }).map((p) => p.id);
  }
  function downloadReport(files) {            // {summary, lines}: one line per preset, in order
    const ok = files.filter((f) => f.ok).length;
    return {summary: downloadSummary(ok, files.length - ok), lines: files.map((f) => (f.ok ? downloadedLine(f.file_name) : f.error))};
  }

  // ---------------------------------------------------------------- S3 geometry (CONTRACT-s3-crop C1-C4, C22-C26)
  // The one rule is the core's Geometry (darkroom/_geometry.py); this mirrors it on the same case tables
  // (tests/cases/s3_geometry_cases.json, s3_geometry_actions.json), so the box on screen is the box exported.
  const GEOMETRY_IDENTITY = {rotate: 0, flip: false, angle: 0, aspect: 'original', crop: null};
  const CROP_EDGES = ['left', 'top', 'right', 'bottom'];
  const RATIO_TOL = 0.001;                                   // verbatim (C3 step 2)
  const CROP_DRAFT_LIMIT = 50;                               // verbatim: the crop mode's own undo steps
  const CROP_MIN_PX = 32;                                    // verbatim: the smallest box on screen
  const CROP_KEY_STEP = 0.005, CROP_KEY_STEP_BIG = 0.05;     // verbatim: arrow keys 0.5 %, Shift 5 %
  const ANGLE_STEP = 0.1;                                    // verbatim: the straighten slider
  const CROP_LABEL = '裁切';
  const CROP_HINT = '拖曳框或把手調整範圍；Enter 完成、Esc 取消';
  const AB_DISABLED_CROP = '裁切模式中不能對照，完成或取消後再用';
  const PASTE_GEOMETRY_LABEL = '連同裁切與旋轉';
  const PASTE_GEOMETRY_NOTE = '（連同裁切與旋轉）';
  const BADGE_ONLY_GEOMETRY = '只有裁切／旋轉';
  const BADGE_CROPPED = '・已裁切';
  const ORIENT_PORTRAIT = '直式', ORIENT_LANDSCAPE = '橫式';
  // C23 constant "比例選單": the values as listed (portrait); a landscape draft shows each ratio turned (5:4, 7:5 ...)
  const ASPECTS = [['original', '原始'], ['free', '自由'], ['1:1', '1:1'], ['4:5', '4:5（8×10）'], ['5:7', '5:7'],
                   ['2:3', '2:3（4×6）'], ['3:4', '3:4'], ['16:9', '16:9']];

  const gcd = (a, b) => { while (b) { [a, b] = [b, a % b]; } return a; };
  function reduceAspect(a) {
    const m = /^(\d+):(\d+)$/.exec(a || '');
    if (!m) return a;
    const w = parseInt(m[1], 10), h = parseInt(m[2], 10), k = gcd(w, h);
    return `${w / k}:${h / k}`;
  }
  const turnAspect = (a) => (a === 'original' || a === 'free' ? a : a.split(':').reverse().join(':'));

  function fullGeometry(g) {             // a complete object (the crop mode's draft never lacks a key)
    if (!g) return copy(GEOMETRY_IDENTITY);
    return {rotate: g.rotate || 0, flip: !!g.flip, angle: g.angle || 0, aspect: g.aspect || 'original',
            crop: g.crop ? {left: g.crop.left, top: g.crop.top, right: g.crop.right, bottom: g.crop.bottom} : null};
  }
  const isIdentityGeometry = (g) => !g || (!(g.rotate) && !g.flip && !(g.angle) && !g.crop);
  function normGeometry(g) {             // C1: identity -> null (aspect alone is nothing), the ratio reduced
    if (isIdentityGeometry(g)) return null;
    const f = fullGeometry(g);
    f.aspect = reduceAspect(f.aspect);
    return f;
  }
  const frameSize = (g, W, H) => ((g.rotate === 90 || g.rotate === 270) ? [H, W] : [W, H]);
  function ratioOf(g, W, H) {
    const [fw, fh] = frameSize(g, W, H);
    if (g.aspect === 'original' || g.aspect === 'free') return fw / fh;
    const [a, b] = g.aspect.split(':').map(Number);
    return a / b;
  }
  const rad = (deg) => deg * (Math.PI / 180);                // as Python's math.radians: x * (pi / 180)
  const rotv = (phi, x, y) => { const c = Math.cos(phi), s = Math.sin(phi); return [c * x - s * y, s * x + c * y]; };

  function cropLimits(angle, m, e, fw, fh) {   // largest s: the box m +- s*e inside the canvas and the picture
    const th = rad(angle), cx = fw / 2, cy = fh / 2;
    const d = [m[0] - cx, m[1] - cy];
    const a = rotv(-th, d[0], d[1]);
    let best = Infinity;
    for (const sx of [1, -1]) {
      for (const sy of [1, -1]) {
        const ek = [sx * e[0], sy * e[1]];
        const bk = rotv(-th, ek[0], ek[1]);
        for (const [val, half, pos] of [[bk[0], cx, a[0]], [bk[1], cy, a[1]], [ek[0], cx, d[0]], [ek[1], cy, d[1]]]) {
          if (val !== 0) best = Math.min(best, (half - Math.sign(val) * pos) / Math.abs(val));
        }
      }
    }
    return Math.max(0, best);
  }
  function inPicture(angle, m, fw, fh) {
    const a = rotv(-rad(angle), m[0] - fw / 2, m[1] - fh / 2);
    return Math.abs(a[0]) <= fw / 2 && Math.abs(a[1]) <= fh / 2;
  }

  // C3: the crop box of geometry g on a W x H photo -> {left, top, right, bottom, width, height (pixels), box (0..1)}
  function fitCrop(geometry, W, H) {
    const g = fullGeometry(geometry);
    const [fw, fh] = frameSize(g, W, H);
    const rho = ratioOf(g, W, H);
    let m, hw, hh;
    if (!g.crop) {                                              // (1) the largest centred box
      m = [fw / 2, fh / 2];
      const e = [rho / 2, 0.5];
      const s = cropLimits(g.angle, m, e, fw, fh);
      hw = s * e[0]; hh = s * e[1];
    } else {
      const {left: l, top: t, right: r, bottom: b} = g.crop;
      m = [(l + r) / 2 * fw, (t + b) / 2 * fh];
      let w = (r - l) * fw, h = (b - t) * fh;
      if (g.aspect !== 'free' && Math.abs(w / h - rho) / rho > RATIO_TOL) {   // (2) same centre and area
        const area = w * h;
        w = Math.sqrt(area * rho); h = Math.sqrt(area / rho);
      }
      if (!inPicture(g.angle, m, fw, fh)) m = [fw / 2, fh / 2];             // (3)
      const s = Math.min(1, cropLimits(g.angle, m, [w / 2, h / 2], fw, fh));  // (4) shrink only
      hw = s * w / 2; hh = s * h / 2;
    }
    const x0 = m[0] - hw, y0 = m[1] - hh, x1 = m[0] + hw, y1 = m[1] + hh;
    const box = [x0 / fw, y0 / fh, x1 / fw, y1 / fh];
    let L = Math.floor(x0 + 0.5), T = Math.floor(y0 + 0.5), R = Math.floor(x1 + 0.5), B = Math.floor(y1 + 0.5);   // (5)
    L = Math.min(Math.max(L, 0), fw - 1); T = Math.min(Math.max(T, 0), fh - 1);
    R = Math.min(Math.max(R, L + 1), fw); B = Math.min(Math.max(B, T + 1), fh);
    return {left: L, top: T, right: R, bottom: B, width: R - L, height: B - T, box};
  }
  const boxCrop = (b) => ({left: b[0], top: b[1], right: b[2], bottom: b[3]});

  // C4 constant "操作表": rotate / flip / orientation change only the geometry object (the box follows the picture)
  function geometryAction(geometry, action, W, H) {
    const g = fullGeometry(geometry);
    const c = g.crop;
    let box = c ? [c.left, c.top, c.right, c.bottom] : null;
    if (action === 'rotate_right' || action === 'rotate_left') {
      const plus = (action === 'rotate_right') !== g.flip;
      g.rotate = (((g.rotate + (plus ? 90 : -90)) % 360) + 360) % 360;
      if (box) { const [l, t, r, b] = box; box = action === 'rotate_right' ? [1 - b, l, 1 - t, r] : [t, 1 - r, b, 1 - l]; }
      g.aspect = turnAspect(g.aspect);
    } else if (action === 'flip_h' || action === 'flip_v') {
      g.flip = !g.flip;
      g.angle = g.angle ? -g.angle : 0;
      if (action === 'flip_v') g.rotate = (g.rotate + 180) % 360;
      if (box) { const [l, t, r, b] = box; box = action === 'flip_h' ? [1 - r, t, 1 - l, b] : [l, 1 - b, r, 1 - t]; }
    } else if (action === 'orient') {
      if (g.aspect === 'free' || g.aspect === '1:1') return g;
      const [fw, fh] = frameSize(g, W, H);
      const turned = g.aspect === 'original' ? `${fh / gcd(fw, fh)}:${fw / gcd(fw, fh)}` : turnAspect(g.aspect);
      const start = fitCrop(g, W, H).box;
      g.aspect = turned;
      g.crop = boxCrop(start);
      box = fitCrop(g, W, H).box;
    } else {
      throw new Error('unknown geometry action ' + action);
    }
    if (box) g.crop = boxCrop(box);
    return g;
  }

  // the orientation the draft's ratio has now, and the ratio menu for it (C23)
  function cropOrientation(g, W, H) {
    const r = ratioOf(fullGeometry(g), W, H);
    return r < 1 ? 'portrait' : r > 1 ? 'landscape' : 'square';
  }
  function aspectOptions(landscape) {
    return ASPECTS.map(([v, label]) => {
      if (!landscape || v === 'original' || v === 'free' || v === '1:1') return [v, label];
      const t = turnAspect(v);
      const m = /（(\d+)×(\d+)）/.exec(label);
      return [t, t + (m ? `（${m[2]}×${m[1]}）` : '')];
    });
  }

  // C23: dragging a handle (n, s, e, w, ne, nw, se, sw) or the box (move) by dx, dy (0..1 of the frame); a locked
  // ratio holds; the box stops where the picture ends; the result always passes fitCrop (C3).
  function cropBoxFits(g, box, W, H) {
    const t = fullGeometry(g);
    t.aspect = 'free'; t.crop = boxCrop(box);
    if (!(box[0] >= 0 && box[1] >= 0 && box[2] <= 1 && box[3] <= 1 && box[0] < box[2] && box[1] < box[3])) return false;
    const r = fitCrop(t, W, H).box;
    return r.every((v, i) => Math.abs(v - box[i]) < 1e-9);
  }
  function resizedBox(box, handle, dx, dy, rn, minW, minH) {
    let [l, t, r, b] = box;
    if (handle === 'move') return [l + dx, t + dy, r + dx, b + dy];
    const W_ = handle.includes('w'), E_ = handle.includes('e'), N_ = handle.includes('n'), S_ = handle.includes('s');
    if (W_) l += dx; if (E_) r += dx; if (N_) t += dy; if (S_) b += dy;
    let w = Math.max(r - l, minW), h = Math.max(b - t, minH);
    if (rn) {
      const horiz = W_ || E_, vert = N_ || S_;
      if (horiz && vert) { if (w / rn >= h) h = w / rn; else w = h * rn; } else if (horiz) h = w / rn; else w = h * rn;
      if (w < minW) { w = minW; h = w / rn; }
      if (h < minH) { h = minH; w = h * rn; }
      if (horiz && !vert) { const cy = (box[1] + box[3]) / 2; t = cy - h / 2; b = cy + h / 2; }
      if (vert && !horiz) { const cx = (box[0] + box[2]) / 2; l = cx - w / 2; r = cx + w / 2; }
    }
    if (W_) l = r - w; else r = l + w;                         // the opposite edge stays where it was
    if (N_) t = b - h; else b = t + h;
    return [l, t, r, b];
  }
  function cropDrag(draft, size, handle, dx, dy) {
    const W = size.width, H = size.height;
    const g = fullGeometry(draft);
    const start = fitCrop(g, W, H).box;
    const [fw, fh] = frameSize(g, W, H);
    const rn = g.aspect === 'free' ? null : ratioOf(g, W, H) * fh / fw;       // the ratio in 0..1 units
    const at = (k) => resizedBox(start, handle, dx * k, dy * k, rn, size.minW || 0, size.minH || 0);
    let box = at(1);
    if (!cropBoxFits(g, box, W, H)) {                         // as far as the drag still fits
      let lo = 0, hi = 1;
      for (let i = 0; i < 40; i++) { const mid = (lo + hi) / 2; if (cropBoxFits(g, at(mid), W, H)) lo = mid; else hi = mid; }
      box = at(lo);
    }
    g.crop = boxCrop(box);
    g.crop = boxCrop(fitCrop(g, W, H).box);                    // C3 decides
    return g;
  }
  function cropKeyMove(key, shift) {    // the focused box: arrows move it 0.5 % (Shift 5 %); null = not ours
    const s = shift ? CROP_KEY_STEP_BIG : CROP_KEY_STEP;
    return {ArrowLeft: [-s, 0], ArrowRight: [s, 0], ArrowUp: [0, -s], ArrowDown: [0, s]}[key] || null;
  }

  // C22: the crop mode's draft and its own undo (never the reducer). commit / cancel end it; result.changed says
  // whether one setGeometry step is due. A crop null with a chosen ratio becomes the box itself on commit.
  function commitGeometry(draft, W, H) {
    const g = fullGeometry(draft);
    if (!g.crop && g.aspect !== 'original' && g.aspect !== 'free') g.crop = boxCrop(fitCrop(g, W, H).box);
    return normGeometry(g);
  }
  function cropSession(s, ev) {
    switch (ev.type) {
      case 'enter':
        return {active: true, entry: normGeometry(ev.geometry), draft: fullGeometry(ev.geometry), past: [], future: [],
                gesture: null, result: null};
      case 'change': {
        if (!s || !s.active) return s;
        const next = fullGeometry(ev.draft);
        const continuing = !!ev.gesture && s.gesture === ev.gesture;
        if (same(next, s.draft)) return continuing ? s : Object.assign({}, s, {gesture: ev.gesture || null});
        const past = continuing ? s.past : s.past.concat([s.draft]).slice(-CROP_DRAFT_LIMIT);
        return Object.assign({}, s, {draft: next, past, future: [], gesture: ev.gesture || null});
      }
      case 'endGesture':
        return s && s.gesture ? Object.assign({}, s, {gesture: null}) : s;
      case 'undo':
        if (!s || !s.active || !s.past.length) return s;
        return Object.assign({}, s, {draft: s.past[s.past.length - 1], past: s.past.slice(0, -1),
                                     future: s.future.concat([s.draft]), gesture: null});
      case 'redo':
        if (!s || !s.active || !s.future.length) return s;
        return Object.assign({}, s, {draft: s.future[s.future.length - 1], future: s.future.slice(0, -1),
                                     past: s.past.concat([s.draft]), gesture: null});
      case 'reset':
        return cropSession(s, {type: 'change', draft: null});
      case 'commit': {
        if (!s || !s.active) return s;
        const g = commitGeometry(s.draft, ev.width, ev.height);
        return {active: false, entry: s.entry, draft: null, past: [], future: [], gesture: null,
                result: {changed: !same(g, s.entry), geometry: g}};
      }
      case 'cancel':
        if (!s || !s.active) return s;
        return {active: false, entry: s.entry, draft: null, past: [], future: [], gesture: null,
                result: {changed: false, geometry: s.entry}};
      default:
        throw new Error('unknown crop event ' + ev.type);
    }
  }

  const carryGeometry = () => null;     // C24: a photo switch never carries a crop over
  // C25: the original's preview is cached per photo and geometry (and frame for the crop mode)
  const originalKey = (imageId, geometry, frame) => `${imageId}|${JSON.stringify(normGeometry(geometry))}|${frame ? 1 : 0}`;
  const pasteConfirmWith = (sourceName, n, withGeometry) => pasteConfirm(sourceName, n) + (withGeometry ? PASTE_GEOMETRY_NOTE : '');

  return {sliderView, tweakFor, sliderTooltip, clampNote, fmtNum, History, treeKey, matchPreset, presetTitle,
          GEOMETRY_IDENTITY, CROP_EDGES, CROP_DRAFT_LIMIT, CROP_MIN_PX, CROP_KEY_STEP, CROP_KEY_STEP_BIG, ANGLE_STEP,
          CROP_LABEL, CROP_HINT, AB_DISABLED_CROP, PASTE_GEOMETRY_LABEL, PASTE_GEOMETRY_NOTE, BADGE_ONLY_GEOMETRY,
          BADGE_CROPPED, ORIENT_PORTRAIT, ORIENT_LANDSCAPE, ASPECTS, reduceAspect, fullGeometry, isIdentityGeometry,
          normGeometry, frameSize, ratioOf, fitCrop, geometryAction, cropOrientation, aspectOptions, cropBoxFits,
          cropDrag, cropKeyMove, commitGeometry, cropSession, carryGeometry, originalKey, pasteConfirmWith,
          EXPORT_SETTINGS_KEY, EXPORT_FORMATS, FORMAT_LABELS, RESIZE_MODES, RESIZE_LABELS, METADATA_LABELS, REMOVE_GPS_LABEL,
          SHARPEN_TARGETS, SHARPEN_TARGET_LABELS, SHARPEN_AMOUNTS, SHARPEN_AMOUNT_LABELS, NO_RESIZE_LABEL, NO_SHARPEN_LABEL,
          ORIGINAL_SIZE, CUSTOM_PRESET, EXPORT_DEFAULTS, defaultBitDepth, exportPresetSaved, exportPresetUpdated,
          exportPresetDeleted, UNDO_LABEL, EXPORT_PRESET_NAME_PROMPT, resizeTarget, settingsFromForm, exportSettingsFrom,
          exportDialogState, exportSummary, exportRequest, sameSettings,
          CAP_ORDER, CAP_LABELS, CAP_OK, CAP_AVAILABLE, CAP_REFRESH, capStatus, capOff, capButtonText, capLine, capReason,
          DOWNLOAD_XMP, DOWNLOAD_GROUP_XMP, PRESET_IDS_MAX, downloadSummary, downloadedLine, downloadTooMany, idBatches, groupPresetIds,
          downloadReport,
          HISTORY_LIMIT, initialEditor, reduce, strengthEnabled, strengthInEffect, canUndo, canRedo, carryHintVisible,
          parseValueInput, curveAtStrength, curvePath,
          EXPORT_BUSY, EXPORT_DEFAULT_QUALITY, baseName, exportDone, exportFailed, exportBody, exportMessage,
          USER_GROUP, FAV_EMPTY, UPLOAD_BATCH_CHARS, presetSaved, importSummary, importedLine, canSavePreset, favMark,
          groupCreated, saveBody, uploadBatches, importReport,
          explain, EXPLAIN_EXACT, EXPLAIN_PREFIX, openFailed, SAVE_RETRY_MS, retryDue, unloadJobs, CARRY_HINT, CARRY_HINT_SHORT, GRID_EMPTY,
          sliderVars, strengthVars, bipolar, HUE_DOTS, hueDot, CANVASES, CANVAS_STORAGE_KEY, canvasFrom,
          AB_KEY, AB_STORAGE_KEY, AB_DEFAULT_SPLIT, abStep, abSplitFrom,
          FILTERS, FILTER_LABELS, badgeTitle, stale, gridFilter, onlyShown, gridPending, resetConfirm, resetDone, restoreDone,
          RESET_TOAST, RESTORE_TOAST,
          AUTOSAVE_MS, PRESET_CHANGED, PRESET_MISSING, presetStatusText, copied, pasteConfirm, pasteDone,
          exportSelectedDone, gridCount, editBody, editRequest, detailFromSnapshot, gridSelect, exportItems,
          saveEditFailed, loadEditFailed, loadFolderFailed, EDIT_UNREADABLE, saveAllowed};
});
