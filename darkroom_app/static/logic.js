// darkroom front-end logic without DOM access (shared by the page and the node:test suite).
// Contract R3 (slider semantics), R5 (undo history), R6 (tree keyboard, search, typed values, curves),
// CONTRACT-export X13 (export request and messages).
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
  // ed = {presetId, strength, tweaks, past: [snapshot], future: [snapshot], gesture: string|null}
  // A snapshot is {presetId, strength, tweaks}. Every change records the state before it, except further
  // steps of the same gesture (one drag = one step). Changes that change nothing record nothing.
  const HISTORY_LIMIT = 200;
  const snap = (ed) => ({presetId: ed.presetId, strength: ed.strength, tweaks: Object.assign({}, ed.tweaks)});

  function initialEditor() {
    return {presetId: null, strength: 100, tweaks: {}, past: [], future: [], gesture: null};
  }

  const strengthEnabled = (ed) => ed.presetId !== null;
  const strengthInEffect = (ed) => (ed.presetId === null ? 100 : ed.strength);
  const canUndo = (ed) => ed.past.length > 0;
  const canRedo = (ed) => ed.future.length > 0;
  const carryHintVisible = (ed, hasImage) =>
    !!hasImage && (ed.presetId !== null || Object.keys(ed.tweaks).length > 0);

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
      case 'endGesture':
        return ed.gesture ? Object.assign({}, ed, {gesture: null}) : ed;
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
  function matchPreset(p, query) {
    const terms = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
    const hay = (p.name + ' ' + (p.group || '')).toLowerCase();
    return terms.every((t) => hay.includes(t));
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

  return {sliderView, tweakFor, sliderTooltip, clampNote, fmtNum, History, treeKey, matchPreset,
          HISTORY_LIMIT, initialEditor, reduce, strengthEnabled, strengthInEffect, canUndo, canRedo, carryHintVisible,
          parseValueInput, curveAtStrength, curvePath,
          EXPORT_BUSY, EXPORT_DEFAULT_QUALITY, baseName, exportDone, exportFailed, exportBody, exportMessage};
});
