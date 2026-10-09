'use strict';
// darkroom editor: preset tree (left), backend-rendered preview (centre), sliders (right).
// Every preview comes from the backend (POST /api/preview); the page never fakes colour changes.
// Pure logic lives in logic.js: every change of preset / strength / tweaks goes through L.reduce (dispatch);
// this file only reads that state and wires the DOM.

const L = window.DarkroomLogic;
const $ = (s) => document.querySelector(s);
const NO_PRESET = '（未選）';
const STRENGTH = {min: 0, max: 200, step: 1};
const NARROW = window.matchMedia('(max-width: 960px)');

const st = {
  presets: [], byId: {}, flags: {}, sliders: [], groups: [], byKey: {}, libGroups: {groups: [], ungrouped: 0},
  image: null, folder: null,
  loading: null,                                                 // S1: an open photo whose edit is not restored yet
  detail: null,
  edit: null, clipboard: null,                                   // the open photo's saved edit; the copied edit (PL15)
  snapshots: {}, fingerprint: null, previous: false, editStatus: null,   // S2 / S4: what the photo library told us
  grid: {folder: null, items: [], sel: new Set(), anchor: 0, filter: 'all', shown: null},   // the thumbnail grid (PLP9, S9)
  search: '', openFolders: {'\u0001fav': true}, openGroups: loadPref('openGroups', {basic: true}), hslTab: 'h', focusKey: null,
  holding: false, originalUrl: null, originalFor: null,
  caps: null, exportPresets: [],                                 // S2: GET /api/capabilities features; the export presets
};
let ed = L.initialEditor();   // {presetId, strength, tweaks, geometry, past, future, gesture}

function loadPref(k, dflt) {
  try { const v = localStorage.getItem('darkroom.' + k); return v ? JSON.parse(v) : dflt; } catch (e) { return dflt; }
}
function savePref(k, v) { try { localStorage.setItem('darkroom.' + k, JSON.stringify(v)); } catch (e) { /* optional */ } }

let toastT = null;
function toast(msg, err, original) {    // S14: the shown sentence is Chinese; the original sits in the tooltip
  const t = $('#toast'); t.textContent = L.explain(msg); t.title = original || msg;
  t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toastT); toastT = setTimeout(() => { t.className = ''; }, 2600);
}
function setStatus(msg, cls, detail) {
  const s = $('#status'); s.textContent = msg; s.className = cls || 'mute'; s.title = detail || msg;
}

async function api(method, url, body, extra) {
  // X-Darkroom on every request (PLP11): an <img src> / <script src> from another page cannot add it, and a
  // cross-site fetch that adds it needs a CORS preflight the server never answers.
  const r = await fetch(url, Object.assign({method, headers: Object.assign({'X-Darkroom': '1'}, body ? {'Content-Type': 'application/json'} : {}),
                                            body: body ? JSON.stringify(body) : undefined}, extra || {}));
  if (!r.ok) {
    let msg = r.status + '';
    try { msg = (await r.json()).error || msg; } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  return r;
}

// ------------------------------------------------------------------ state (R5): dispatch -> L.reduce -> sync DOM
function refreshUndo() { $('#undo').disabled = !L.canUndo(ed); $('#redo').disabled = !L.canRedo(ed); }
function renderHint() { $('#carry-hint').hidden = !L.carryHintVisible(ed, !!st.image, !!st.edit); }   // S11
function refreshRestorePrevious() {   // S10
  $('#restore-previous-btn').disabled = !(st.image && !st.edit && st.previous);
  capGate($('#restore-previous-btn'), capReasonOf('photo_library'));   // S2 E23: the photo library is off
}

// ------------------------------------------------------------------ S2 capabilities (E22, E23, E30): off = disabled with
// the reason as the tooltip, never hidden (H11)
const capReasonOf = (key) => L.capReason(st.caps, key);
function capGate(el, reason) {
  if (!el) return;
  if (reason !== null) {
    if (!('title0' in el.dataset)) el.dataset.title0 = el.title;
    el.disabled = true; el.title = reason;
  } else if ('title0' in el.dataset) { el.title = el.dataset.title0; delete el.dataset.title0; }
}

let capsShown = false;                  // E23: the photo library / GPU sentence goes to the status line once
async function loadCaps(refresh) {
  try { st.caps = (await (await api('GET', '/api/capabilities' + (refresh ? '?refresh=1' : ''))).json()).features; }
  catch (e) { toast(e.message, true); return; }
  renderCaps();
  refreshCopy(); refreshSavePreset(); refreshRestorePrevious(); refreshExport(); refreshLibraryGates(); renderTree();
  if (!capsShown) {
    capsShown = true;
    const off = capReasonOf('photo_library') !== null ? 'photo_library' : capReasonOf('gpu') !== null ? 'gpu' : null;
    if (off) setStatus(L.capLine(off, st.caps[off]), off === 'photo_library' ? 'err' : 'mute');
  }
}

function renderCaps() {
  const b = $('#cap-btn');
  b.textContent = L.capButtonText(st.caps);
  b.classList.toggle('off', L.capOff(st.caps).length > 0);
  const list = $('#cap-list');
  list.innerHTML = '';
  for (const k of L.CAP_ORDER) {
    const f = st.caps && st.caps[k];
    if (!f) continue;
    const li = document.createElement('li');
    li.className = f.available ? 'ok' : 'off';
    li.textContent = L.capLine(k, f);
    list.appendChild(li);
  }
}

function toggleCapDetail(on) {
  const box = $('#cap-detail');
  box.hidden = on === undefined ? !box.hidden : !on;
  $('#cap-btn').setAttribute('aria-expanded', String(!box.hidden));
  if (!box.hidden) $('#cap-refresh').focus();
}

function refreshLibraryGates() {         // E20 / E23: organising the preset library is off -> disabled, reason as tooltip
  const r = capReasonOf('preset_library_writes');
  for (const id of ['#import-btn', '#new-group-btn']) {
    if (r === null && $(id).dataset.title0 !== undefined) $(id).disabled = false;
    capGate($(id), r);
  }
}

async function dispatch(action, opts) {
  const prev = ed;
  ed = L.reduce(ed, action);
  if (ed === prev) return;
  refreshUndo();
  renderHint();
  refreshSavePreset();
  const sameState = prev.presetId === ed.presetId && prev.strength === ed.strength &&
    JSON.stringify(prev.tweaks) === JSON.stringify(ed.tweaks) &&
    JSON.stringify(prev.geometry) === JSON.stringify(ed.geometry);           // S3 C24: the geometry is state too
  if (sameState) return;
  if (!(opts && opts.restore)) scheduleSave();          // PL15: every change is saved; restoring one is not a change
  if (prev.presetId !== ed.presetId) {
    requestPreview();
    await loadPreset(ed.presetId);
    renderSliders();
    return;
  }
  if (prev.strength !== ed.strength) renderStrength();
  refreshSliderValues();
  refreshBadges();
  requestPreview();
}
const undo = () => (cropActive() ? cropStep('undo') : dispatch({type: 'undo'}));   // C22: the draft has its own
const redo = () => (cropActive() ? cropStep('redo') : dispatch({type: 'redo'}));

// ------------------------------------------------------------------ slider values (R3)
function presetValue(key) {
  const s = st.byKey[key];
  return st.detail && st.detail.values[key] != null ? st.detail.values[key] : s.default;
}
const strengthNow = () => L.strengthInEffect(ed);
function view(key) { return L.sliderView(st.byKey[key], presetValue(key), strengthNow(), ed.tweaks[key] || 0); }
const setValue = (key, value, gesture) =>
  dispatch({type: 'setValue', slider: st.byKey[key], presetValue: presetValue(key), value, gesture});

// ------------------------------------------------------------------ preview: latest wins
// Only the newest parameters wait to be sent; older ones are overwritten, never queued.
const pv = {pending: null, inflight: false, seq: 0, shownSeq: 0, url: null};

function currentRequest() {             // S3 C19 / C24: the geometry on screen always goes with it (null too)
  const overrides = {};
  for (const [k, d] of Object.entries(ed.tweaks)) if (d) overrides[k] = d;
  return {image_id: st.image.image_id, preset_id: ed.presetId, strength: strengthNow(), overrides,
          geometry: L.normGeometry(ed.geometry)};
}

function requestPreview() {
  if (!st.image) return;
  const frame = cropActive();           // C22: the crop mode shows the whole straightened frame
  pv.pending = {body: frame ? frameRequest() : currentRequest(), seq: ++pv.seq, kind: frame ? 'frame' : 'edit'};
  if (!pv.inflight) pump();
}

async function pump() {
  pv.inflight = true;
  setStatus('算圖中…', 'busy');
  try {
    while (pv.pending) {
      const job = pv.pending; pv.pending = null;
      const t0 = performance.now();
      let r;
      try { r = await api('POST', '/api/preview', job.body); } catch (e) { setStatus(L.explain('預覽失敗：' + e.message), 'err', e.message); continue; }
      const ms = r.headers.get('X-Render-Ms');
      const blob = await r.blob();
      if (job.seq < pv.shownSeq) continue;
      pv.shownSeq = job.seq;
      const url = URL.createObjectURL(blob);
      pv.kind = job.kind;
      if (!st.holding) { await swapImage($('#preview-img'), url); $('#preview-img').dataset.kind = job.kind; layoutCrop(); }
      if (pv.url) URL.revokeObjectURL(pv.url);
      pv.url = url;
      if (!pv.pending) {
        const rt = performance.now() - t0;
        setStatus('已更新', 'mute', `預覽已更新：後端 ${(+ms).toFixed(0)} ms，往返 ${rt.toFixed(0)} ms`);   // S17: ms in the tooltip
      }
    }
  } finally {
    pv.inflight = false;
  }
}

function swapImage(img, url) {
  return new Promise((resolve) => {
    const tmp = new Image();
    tmp.onload = () => { img.src = url; img.hidden = false; $('#preview-empty').hidden = true; resolve(); };
    tmp.onerror = () => resolve();
    tmp.src = url;
  });
}

function originalRequest() {           // S7' (C25): the same geometry, no colour; the crop mode's own frame
  const frame = cropActive();
  const g = frame ? Object.assign({}, crop.s.draft, {crop: null}) : ed.geometry;
  const body = {image_id: st.image.image_id, preset_id: null, strength: 100, overrides: {}, geometry: L.normGeometry(g)};
  if (frame) body.frame = true;
  return {body, key: L.originalKey(st.image.image_id, g, frame)};
}

async function ensureOriginal() {      // the untouched preview of the open photo (shared by hold and compare)
  if (!st.image) return false;
  const id = st.image.image_id;
  const {body, key} = originalRequest();
  if (st.originalFor === key) return true;
  const r = await api('POST', '/api/preview', body);
  const blob = await r.blob();
  if (!st.image || st.image.image_id !== id) return false;
  if (st.originalUrl) URL.revokeObjectURL(st.originalUrl);
  st.originalUrl = URL.createObjectURL(blob);
  st.originalFor = key;
  return true;
}

async function showOriginal(on) {
  if (!st.image) return;
  st.holding = on;
  $('#pv-label').hidden = !on;
  $('#hold').classList.toggle('on', on);
  const img = $('#preview-img');
  if (!on) { if (pv.url) { img.src = pv.url; img.dataset.kind = pv.kind || 'edit'; } return; }
  if (!(await ensureOriginal())) return;
  if (st.holding) img.src = st.originalUrl;
}

// ------------------------------------------------------------------ S7 A/B compare: the original over the edited
// picture, clipped at the split; dragging the divider never asks the backend for anything. Not editor state: it
// stays out of L.reduce and the undo history; the split survives a photo switch (sessionStorage).
const ab = {on: false, split: L.AB_DEFAULT_SPLIT};

function abLayout() {
  const img = $('#preview-img'), orig = $('#ab-orig'), wrap = $('#preview');
  if (!ab.on || img.hidden) return;
  const l = img.offsetLeft, t = img.offsetTop, w = img.offsetWidth, h = img.offsetHeight;
  Object.assign(orig.style, {left: l + 'px', top: t + 'px', width: w + 'px', height: h + 'px'});
  orig.style.setProperty('--split', (ab.split * 100).toFixed(3) + '%');
  Object.assign($('#ab-divider').style, {left: (l + ab.split * w) + 'px', top: t + 'px', bottom: (wrap.clientHeight - t - h) + 'px'});
  $('#ab-tag-a').style.left = (l + 10) + 'px'; $('#ab-tag-a').style.top = (t + 10) + 'px';
  $('#ab-tag-b').style.right = (wrap.clientWidth - l - w + 10) + 'px'; $('#ab-tag-b').style.top = (t + 10) + 'px';
  $('#ab-handle').setAttribute('aria-valuenow', String(Math.round(ab.split * 100)));
}

async function abToggle(on) {
  const want = on === undefined ? !ab.on : !!on;
  if (want && (!st.image || cropActive())) return;      // C25 (D9): never while cropping
  if (want) {
    if (!(await ensureOriginal())) return;
    const orig = $('#ab-orig');
    if (orig.src !== st.originalUrl) await new Promise((res) => { orig.onload = res; orig.onerror = res; orig.src = st.originalUrl; });
  }
  ab.on = want;
  $('#preview').classList.toggle('ab', ab.on);
  $('#ab-btn').classList.toggle('on', ab.on);
  $('#ab-btn').setAttribute('aria-pressed', String(ab.on));
  abLayout();
}

function abSetSplit(v) {
  ab.split = Math.min(1, Math.max(0, v));
  try { sessionStorage.setItem(L.AB_STORAGE_KEY, String(ab.split)); } catch (e) { /* optional */ }
  abLayout();
}

function abMoveTo(clientX) {
  const r = $('#preview-img').getBoundingClientRect();
  abSetSplit((clientX - r.left) / r.width);
}

function abRefresh() {                   // after a photo switch or a new geometry: the original is another picture
  if (!ab.on) return;
  if (!st.image) { abToggle(false); return; }
  if (st.originalFor !== originalRequest().key) abToggle(true); else abLayout();
}

function refreshAb() {                   // S7 / C25: disabled without a photo and in the crop mode (reason as tooltip)
  const b = $('#ab-btn');
  if (!('title0' in b.dataset)) b.dataset.title0 = b.title;
  b.disabled = !st.image || cropActive();
  b.title = cropActive() ? L.AB_DISABLED_CROP : b.dataset.title0;
}

function initCompare() {
  try { ab.split = L.abSplitFrom(sessionStorage.getItem(L.AB_STORAGE_KEY)); } catch (e) { /* optional */ }
  const div = $('#ab-divider'), wrap = $('#preview');
  div.addEventListener('pointerdown', (e) => {
    e.preventDefault(); div.setPointerCapture(e.pointerId); wrap.classList.add('dragging'); abMoveTo(e.clientX);
    const mv = (ev) => abMoveTo(ev.clientX);
    const up = () => { wrap.classList.remove('dragging'); div.removeEventListener('pointermove', mv); div.removeEventListener('pointerup', up); };
    div.addEventListener('pointermove', mv); div.addEventListener('pointerup', up);
  });
  div.addEventListener('dblclick', () => abSetSplit(L.AB_DEFAULT_SPLIT));
  $('#ab-handle').addEventListener('keydown', (e) => {
    const v = L.abStep(ab.split, e.key, e.shiftKey);
    if (v === null) return;
    e.preventDefault(); abSetSplit(v);
  });
  $('#ab-btn').onclick = () => abToggle();
  if (typeof ResizeObserver === 'function') new ResizeObserver(abLayout).observe(wrap);
  $('#preview-img').addEventListener('load', abRefresh);
}

// ------------------------------------------------------------------ preset tree (R4 flags, R6 keyboard)
function splitGroup(group) {
  const g = (group || '').trim();
  if (!g) return ['（未分組）', null];
  const i = g.indexOf(' - ');
  return i < 0 ? [g, null] : [g.slice(0, i), g.slice(i + 3)];
}

function buildTree() {
  const root = new Map();
  for (const g of st.libGroups.groups) {            // K10: explicit groups show even when empty
    if (!root.has(g.name)) root.set(g.name, {subs: new Map(), items: []});
    for (const c of g.children) if (!root.get(g.name).subs.has(c.name)) root.get(g.name).subs.set(c.name, []);
  }
  for (const p of st.presets) {
    const [top, sub] = splitGroup(p.group);
    if (!root.has(top)) root.set(top, {subs: new Map(), items: []});
    const node = root.get(top);
    if (sub === null) node.items.push(p);
    else { if (!node.subs.has(sub)) node.subs.set(sub, []); node.subs.get(sub).push(p); }
  }
  return root;
}

function flagHtml(p) {
  if (!p.supported) return '<span class="flag major" title="不支援的 preset">⛔</span>';
  const lv = st.flags[p.id];
  if (lv === 'major') return '<span class="flag major" title="有會改變觀感的設定無法套用">⚠</span>';
  if (lv === 'minor') return '<span class="flag minor" title="有細節設定（雜色減少、銳利化細節等）未套用">·</span>';
  return '';
}

let treeRows = [];   // visible rows: {el, type, key, depth, open, parent, id}

function addRow(el, meta) {
  el.tabIndex = -1;
  el.setAttribute('role', 'treeitem');
  el.setAttribute('aria-level', String(meta.depth + 1));
  if (meta.type === 'folder') el.setAttribute('aria-expanded', String(!!meta.open));
  el.dataset.row = String(treeRows.length);
  treeRows.push(Object.assign({el}, meta));
  $('#preset-tree').appendChild(el);
}

function presetEl(p, depth, showPath) {
  const el = document.createElement('div');
  el.className = 'tnode preset' + (p.id === ed.presetId ? ' active' : '') + (p.supported ? '' : ' unsupported');
  el.style.paddingLeft = (6 + depth * 14) + 'px';
  el.dataset.id = p.id;
  el.innerHTML = `<span class="tw"></span><span class="nm"></span>${flagHtml(p)}` + (showPath ? '<span class="path"></span>' : '') +
    `<span class="sp"></span><button class="fav" tabindex="-1" aria-pressed="${!!p.favorite}" title="${p.favorite ? '移除最愛' : '加入最愛'}">${L.favMark(p.favorite)}</button>` +
    '<button class="row-menu" tabindex="-1" title="動作：改名、搬到…、新群組" aria-haspopup="menu">⋯</button>';
  el.querySelector('.nm').textContent = p.name;
  if (showPath) el.querySelector('.path').textContent = p.group;
  el.title = L.presetTitle(p);
  el.querySelector('.fav').onclick = (e) => { e.stopPropagation(); toggleFavorite(p); };
  capGate(el.querySelector('.fav'), capReasonOf('preset_library_writes'));   // S2 E20: disabled, never hidden
  el.querySelector('.row-menu').onclick = (e) => { e.stopPropagation(); presetMenu(p, e.currentTarget); };
  if (p.supported) el.onclick = () => { st.focusKey = 'p:' + p.id; selectPreset(p.id); };
  return el;
}

function folderEl(name, key, count, depth, path) {
  const open = !!st.openFolders[key];
  const el = document.createElement('div');
  el.className = 'tnode folder';
  el.style.paddingLeft = (6 + depth * 14) + 'px';
  el.innerHTML = `<span class="tw">${open ? '▼' : '▶'}</span><span class="nm"></span><span class="cnt">${count}</span>` +
    (path ? '<span class="sp"></span><button class="row-menu" tabindex="-1" title="動作：群組改名、新群組" aria-haspopup="menu">⋯</button>' : '');
  el.querySelector('.nm').textContent = name;
  if (path) el.querySelector('.row-menu').onclick = (e) => { e.stopPropagation(); groupMenu(path, e.currentTarget); };
  el.onclick = () => { st.focusKey = 'f:' + key; st.openFolders[key] = !open; renderTree(); };
  return el;
}

function renderTree() {
  const box = $('#preset-tree');
  const scroll = box.scrollTop;
  box.innerHTML = '';
  treeRows = [];
  $('#lib-count').textContent = `preset 庫（${st.presets.length} 個）`;
  const none = document.createElement('div');
  none.className = 'tnode preset none' + (ed.presetId === null ? ' active' : '');
  none.innerHTML = '<span class="tw"></span><span class="nm">（不套 preset，只用微調）</span>';
  none.onclick = () => { st.focusKey = 'p:'; selectPreset(null); };
  addRow(none, {type: 'preset', key: 'p:', id: null, depth: 0, parent: -1});
  if (st.search) {
    const hits = st.presets.filter((p) => L.matchPreset(p, st.search));
    const n = document.createElement('div');
    n.className = 'sec-title'; n.textContent = `找到 ${hits.length} 個`;
    box.appendChild(n);
    hits.forEach((p) => addRow(presetEl(p, 0, true), {type: 'preset', key: 'p:' + p.id, id: p.id, depth: 0, parent: -1}));
  } else {
    const favs = st.presets.filter((p) => p.favorite);
    const FK = '\u0001fav';
    const favIdx = treeRows.length;
    addRow(folderEl('★ 最愛', FK, favs.length, 0, null), {type: 'folder', key: 'f:' + FK, fkey: FK, depth: 0, open: !!st.openFolders[FK], parent: -1});
    if (st.openFolders[FK]) {
      if (!favs.length) {
        const e = document.createElement('div');
        e.className = 'fav-empty'; e.textContent = L.FAV_EMPTY;
        box.appendChild(e);
      }
      favs.forEach((p) => addRow(presetEl(p, 1, true), {type: 'preset', key: 'p:\u0001' + p.id, id: p.id, depth: 1, parent: favIdx}));
    }
    for (const [top, node] of buildTree()) {
      const count = node.items.length + [...node.subs.values()].reduce((a, l) => a + l.length, 0);
      const topIdx = treeRows.length;
      addRow(folderEl(top, top, count, 0, top === '（未分組）' ? null : top), {type: 'folder', key: 'f:' + top, fkey: top, depth: 0, open: !!st.openFolders[top], parent: -1});
      if (!st.openFolders[top]) continue;
      for (const [sub, list] of node.subs) {
        const key = top + '\u0000' + sub;
        const subIdx = treeRows.length;
        addRow(folderEl(sub, key, list.length, 1, top + ' - ' + sub), {type: 'folder', key: 'f:' + key, fkey: key, depth: 1, open: !!st.openFolders[key], parent: topIdx});
        if (st.openFolders[key]) list.forEach((p) => addRow(presetEl(p, 2, false), {type: 'preset', key: 'p:' + p.id, id: p.id, depth: 2, parent: subIdx}));
      }
      node.items.forEach((p) => addRow(presetEl(p, 1, false), {type: 'preset', key: 'p:' + p.id, id: p.id, depth: 1, parent: topIdx}));
    }
  }
  // roving tabindex: exactly one row can be reached with Tab
  let fi = treeRows.findIndex((r) => r.key === st.focusKey);
  if (fi < 0) fi = treeRows.findIndex((r) => r.type === 'preset' && r.id === ed.presetId);
  if (fi < 0) fi = 0;
  treeRows[fi].el.tabIndex = 0;
  box.scrollTop = scroll;
  return fi;
}

function focusRow(i) {
  const r = treeRows[i];
  if (!r) return;
  treeRows.forEach((x) => { x.el.tabIndex = -1; });
  r.el.tabIndex = 0;
  st.focusKey = r.key;
  r.el.focus();
  r.el.scrollIntoView({block: 'nearest'});
}

function onTreeKey(e) {
  const row = e.target.closest('.tnode');
  if (!row || row.dataset.row === undefined) return;
  const res = L.treeKey(treeRows, +row.dataset.row, e.key);
  if (!res) return;
  e.preventDefault();
  const target = treeRows[res.focus];
  if (res.action === 'apply') {
    if (target.id === null || st.byId[target.id].supported) { st.focusKey = target.key; selectPreset(target.id).then(() => focusRow(treeRows.findIndex((r) => r.key === st.focusKey))); }
    return;
  }
  if (res.action) {
    st.openFolders[target.fkey] = res.action === 'expand' ? true : res.action === 'collapse' ? false : !st.openFolders[target.fkey];
    st.focusKey = target.key;
    focusRow(renderTree());
    return;
  }
  focusRow(res.focus);
}

async function loadPreset(id) {
  st.detail = null;
  if (id !== null) {
    let detail = null;
    try { detail = await (await api('GET', '/api/presets/' + encodeURIComponent(id))).json(); }
    catch (e) { if (!st.snapshots[id]) toast('讀取 preset 失敗：' + e.message, true); }   // missing: the snapshot serves
    if (ed.presetId !== id) return;
    // S3: a remembered snapshot (the photo's saved edit) is the slider baseline, not the library's current file
    st.detail = st.snapshots[id] ? L.detailFromSnapshot(st.snapshots[id], detail) : detail;
  }
  $('#preset-name').textContent = id === null ? NO_PRESET
    : (st.byId[id] ? st.byId[id].name : (st.detail && st.detail.name) || id);
  const banner = $('#skip-banner'), note = $('#skip-note');
  const b = st.detail ? st.detail.banner : '', n = st.detail ? st.detail.note : '';
  banner.textContent = b; banner.title = b; banner.hidden = !b;
  note.textContent = n; note.title = n; note.hidden = !n;
  renderSkipDetail(b, n);
  renderStrength();
  renderTree();
}

function selectPreset(id) { return dispatch({type: 'selectPreset', id}); }   // strength and tweaks are kept (R5)

// S12: the one-line toolbar keeps its height (R4); the full text opens over the preview instead
function renderSkipDetail(banner, note) {
  const box = $('#skip-detail');
  box.innerHTML = '';
  for (const t of [banner, note]) {
    if (!t) continue;
    const p = document.createElement('p'); p.textContent = t; box.appendChild(p);
  }
  if (!banner && !note) box.hidden = true;
}
function toggleSkipDetail(on) {
  const box = $('#skip-detail');
  box.hidden = on === undefined ? !box.hidden : !on;
  if (box.hidden && box.contains(document.activeElement)) $('#skip-banner').focus();
}

// ------------------------------------------------------------------ inline value editing (R6)
function editValue(span, current, spec, commit) {
  if (span.querySelector('input')) return;
  const inp = document.createElement('input');
  inp.type = 'text'; inp.className = 'v-edit'; inp.value = current;
  const old = span.textContent;
  span.textContent = '';
  span.appendChild(inp);
  inp.focus(); inp.select();
  let done = false;
  const finish = (ok) => {
    if (done) return; done = true;
    const v = ok ? L.parseValueInput(inp.value, spec) : null;
    span.textContent = old;
    if (v !== null) commit(v);
  };
  inp.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Enter') finish(true);
    else if (e.key === 'Escape') finish(false);
  });
  inp.addEventListener('blur', () => finish(true));
}

// ------------------------------------------------------------------ sliders
function updateRow(row) {
  const key = row.dataset.key, s = st.byKey[key], v = view(key);
  row.classList.toggle('adjusted', !!ed.tweaks[key]);
  row.classList.toggle('clamped', !!v.clamped);
  row.classList.toggle('at-min', v.clamped === 'min');
  row.classList.toggle('at-max', v.clamped === 'max');
  const inp = row.querySelector('input[type=range]');
  if (document.activeElement !== inp || !row.dragging) inp.value = v.value;
  const vars = L.sliderVars(s, v);       // S17: the preset's mark and the tweak line are drawn from these
  inp.style.setProperty('--base', vars.base); inp.style.setProperty('--lo', vars.lo); inp.style.setProperty('--hi', vars.hi);
  const vs = row.querySelector('.v');
  if (!vs.querySelector('input')) vs.textContent = L.fmtNum(s, v.value);
  row.querySelector('.cn').textContent = L.clampNote(v);
  row.title = L.sliderTooltip(s, presetValue(key), strengthNow(), ed.tweaks[key] || 0);
}

function sliderRow(s) {
  const row = document.createElement('div');
  row.className = 'sl' + (L.bipolar(s) ? ' bipolar' : '');
  row.dataset.key = s.key;
  row.innerHTML = `<label></label><span class="track"><input type="range" min="${s.min}" max="${s.max}" step="${s.step}"></span>` +
    '<span class="vals"><span class="v editable" title="點兩下輸入數值"></span><span class="cn"></span></span>' +
    '<button class="reset" title="還原這一項的微調（回到 preset × 強度）">↺</button>';
  const dot = L.hueDot(s.key);
  if (dot) { const h = document.createElement('span'); h.className = 'hue'; h.style.background = dot; row.querySelector('label').appendChild(h); }
  row.querySelector('label').appendChild(document.createTextNode(s.label));
  const inp = row.querySelector('input');
  inp.setAttribute('aria-label', s.label);
  inp.addEventListener('input', () => { row.dragging = true; setValue(s.key, +inp.value, 'slider:' + s.key); });  // one step per drag
  inp.addEventListener('change', () => { row.dragging = false; dispatch({type: 'endGesture'}); updateRow(row); });
  const reset = () => dispatch({type: 'resetKey', key: s.key});
  inp.addEventListener('dblclick', reset);
  row.querySelector('label').addEventListener('dblclick', reset);
  row.querySelector('.reset').addEventListener('click', reset);
  const vs = row.querySelector('.v');
  vs.addEventListener('dblclick', () => editValue(vs, L.fmtNum(s, view(s.key).value).replace(/^\+/, ''), s, (v) => setValue(s.key, v)));
  updateRow(row);
  return row;
}

function curveBox() {
  const box = document.createElement('div');
  box.className = 'curve-box';
  const curves = (st.detail && st.detail.curves) || {};
  const chans = [['ToneCurvePV2012', '#e0e0e0'], ['ToneCurvePV2012Red', '#ff6060'],
                 ['ToneCurvePV2012Green', '#60d060'], ['ToneCurvePV2012Blue', '#6090ff']];
  const size = 200;
  let paths = '';
  for (const [k, col] of chans) {
    if (!curves[k]) continue;
    const d = L.curvePath(L.curveAtStrength(curves[k], strengthNow()), size);
    paths += `<path d="${d}" fill="none" stroke="${col}" stroke-width="2" stroke-opacity="${k === chans[0][0] ? 1 : 0.85}"/>`;
  }
  box.innerHTML = `<svg viewBox="0 0 ${size} ${size}" role="img" aria-label="preset 的點曲線（唯讀）">` +
    '<g stroke="#333"><path d="M50 0V200M100 0V200M150 0V200M0 50H200M0 100H200M0 150H200"/></g>' +
    `<path d="M0 ${size}L${size} 0" stroke="#555" stroke-dasharray="3 3"/>${paths}</svg>` +
    `<div class="note">${paths ? `點曲線（唯讀，套用強度 ${strengthNow()}%）` : '這個 preset 沒有點曲線'}</div>`;
  return box;
}

function renderSliders() {
  const box = $('#sliders');
  const scroll = box.scrollTop;
  box.innerHTML = '';
  for (const [g, gname] of st.groups) {
    const open = !!st.openGroups[g];
    const acc = document.createElement('div');
    acc.className = 'acc' + (open ? ' open' : '');
    acc.dataset.group = g;
    acc.innerHTML = `<button class="ah" aria-expanded="${open}"><span class="tw">${open ? '▼' : '▶'}</span><span></span><span class="tc"></span></button><div class="ab"></div>`;
    acc.querySelector('.ah span:nth-child(2)').textContent = gname;
    acc.querySelector('.ah').onclick = () => { st.openGroups[g] = !open; savePref('openGroups', st.openGroups); renderSliders(); box.querySelector(`.acc[data-group="${g}"] .ah`).focus(); };
    const ab = acc.querySelector('.ab');
    let list = st.sliders.filter((s) => s.group === g);
    if (g === 'hsl') {
      const tabs = document.createElement('div'); tabs.className = 'tabs';
      for (const [k, n] of [['h', '色相'], ['s', '飽和度'], ['l', '明度']]) {
        const b = document.createElement('button'); b.textContent = n;
        if (st.hslTab === k) b.classList.add('on');
        b.onclick = () => { st.hslTab = k; renderSliders(); };
        tabs.appendChild(b);
      }
      ab.appendChild(tabs);
      list = list.filter((s) => s.sub === st.hslTab);
    }
    if (g === 'curve' && open) ab.appendChild(curveBox());
    if (open) list.forEach((s) => ab.appendChild(sliderRow(s)));
    box.appendChild(acc);
  }
  refreshBadges();
  box.scrollTop = scroll;
}

function refreshBadges() {
  document.querySelectorAll('#sliders .acc').forEach((acc) => {
    const g = acc.dataset.group;
    const n = st.sliders.filter((s) => s.group === g && ed.tweaks[s.key]).length;
    acc.querySelector('.tc').textContent = n ? `微調 ${n} 項` : '';   // the amber dot is drawn by CSS (S17)
  });
}

function refreshSliderValues() {
  document.querySelectorAll('#sliders .sl').forEach(updateRow);
  const cb = document.querySelector('#sliders .curve-box');
  if (cb) cb.replaceWith(curveBox());
}

// ------------------------------------------------------------------ strength
function renderStrength() {
  const on = L.strengthEnabled(ed);
  $('#strength').disabled = !on;
  $('#strength-100').disabled = !on;
  if (document.activeElement !== $('#strength')) $('#strength').value = ed.strength;
  const val = $('#strength-value');
  if (!val.querySelector('input')) {
    val.textContent = on ? String(ed.strength) : '—';
    if (on) { const p = document.createElement('span'); p.className = 'pct'; p.textContent = '%'; val.appendChild(p); }
  }
  const vars = L.strengthVars(on ? ed.strength : 100);   // S17: the dial fills from 100 % toward the thumb
  for (const [k, v] of Object.entries(vars)) $('#strength').style.setProperty('--' + k, v);
  $('#strength').title = on ? '' : '先選一個 preset';
}

function setCanvas(name) {              // S17: the preview background, remembered per browser
  const c = L.canvasFrom(name);
  document.body.dataset.canvas = c;
  for (const b of document.querySelectorAll('.canvas-pick button')) b.setAttribute('aria-pressed', String(b.dataset.canvas === c));
  savePref('canvas', c);
}
const setStrength = (v, gesture) => dispatch({type: 'setStrength', value: v, gesture});

// ------------------------------------------------------------------ preset library (K19): index only, never the files
async function reloadLibrary() {
  const [presets, flags, groups] = await Promise.all([
    api('GET', '/api/presets').then((r) => r.json()),
    api('GET', '/api/preset_flags').then((r) => r.json()),
    api('GET', '/api/preset-library/groups').then((r) => r.json()),
  ]);
  st.presets = presets; st.flags = flags; st.libGroups = groups; st.byId = {};
  presets.forEach((p) => { st.byId[p.id] = p; });
  renderTree();
}

async function libraryCall(path, body, done) {
  try {
    const res = await (await api('POST', '/api/preset-library/' + path, body)).json();
    await reloadLibrary();
    if (done) toast(done(res));
    return res;
  } catch (e) { toast(e.message, true); return null; }
}

const toggleFavorite = (p) => libraryCall('favorite', {preset_id: p.id, favorite: !p.favorite});

function closeMenu() { const m = document.querySelector('.menu-pop'); if (m) m.remove(); }

function showMenu(anchor, items) {
  closeMenu();
  const m = document.createElement('div');
  m.className = 'menu-pop'; m.setAttribute('role', 'menu');
  for (const [label, fn, off] of items) {   // off: the reason the item is disabled (S2 E20), else null / undefined
    const b = document.createElement('button');
    b.setAttribute('role', 'menuitem'); b.textContent = label;
    b.onclick = (e) => { e.stopPropagation(); closeMenu(); fn(); };
    if (off != null) { b.disabled = true; b.title = off; }
    m.appendChild(b);
  }
  const r = anchor.getBoundingClientRect();
  m.style.left = Math.min(r.left, window.innerWidth - 180) + 'px'; m.style.top = (r.bottom + 2) + 'px';
  document.body.appendChild(m);
  const first = m.querySelector('button:not(:disabled)') || m.querySelector('button');
  if (first) first.focus();
  m.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeMenu(); anchor.focus(); } });
}

function askNewGroup(base) {
  const g = prompt('新群組名稱（用「 - 」分層）', base ? base + ' - ' : '');
  if (g !== null) libraryCall('groups/create', {group: g}, (r) => L.groupCreated(r.group));
}

function presetMenu(p, anchor) {
  const off = capReasonOf('preset_library_writes');
  showMenu(anchor, [
    ['改名…', () => { const n = prompt('preset 名稱', p.name); if (n !== null) libraryCall('rename', {preset_id: p.id, name: n}); }, off],
    ['搬到…', () => { const g = prompt('搬到群組（用「 - 」分層）', p.group); if (g !== null) libraryCall('move', {preset_id: p.id, group: g}); }, off],
    ['新群組…', () => askNewGroup(p.group), off],
    [L.DOWNLOAD_XMP, () => downloadPresets([p.id])],                       // S2 E30: the file, never a path
  ]);
}

function groupMenu(path, anchor) {
  const off = capReasonOf('preset_library_writes');
  showMenu(anchor, [
    ['群組改名…', () => { const n = prompt('群組的新名稱（完整路徑）', path); if (n !== null) libraryCall('groups/rename', {group: path, new_name: n}); }, off],
    ['新群組…', () => askNewGroup(path), off],
    [L.DOWNLOAD_GROUP_XMP, () => downloadPresets(L.groupPresetIds(st.presets, path))],   // S2 E30: 500 per request
  ]);
}

// S2 E16 / E30: the page downloads the preset files itself (POST /api/preset-library/files, 1..500 ids per request,
// more in batches); the server never writes them anywhere. One file after another; failures listed in #import-result.
function saveBlob(fileName, base64) {
  const bin = atob(base64), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], {type: 'application/octet-stream'}));
  const a = document.createElement('a');
  a.href = url; a.download = fileName; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

async function downloadPresets(ids) {
  if (!ids.length) return;
  if (ids.length > L.PRESET_IDS_MAX) { toast(L.downloadTooMany(ids.length), true); return; }   // E30 (seal F4)
  const files = [];
  try {
    for (const batch of L.idBatches(ids)) {
      files.push(...(await (await api('POST', '/api/preset-library/files', {preset_ids: batch})).json()).files);
    }
  } catch (e) { toast(e.message, true); }
  if (!files.length) return;
  for (const f of files) {
    if (!f.ok) continue;
    saveBlob(f.file_name, f.data_base64);
    await new Promise((res) => setTimeout(res, 120));   // one after another: the browser keeps every download
  }
  const rep = L.downloadReport(files);
  const box = $('#import-result');
  box.innerHTML = '';
  const head = document.createElement('div'); head.className = 'ir-head'; head.textContent = rep.summary;
  const close = document.createElement('button'); close.className = 'icon'; close.textContent = '×'; close.title = '關閉';
  close.onclick = () => { box.hidden = true; };
  head.appendChild(close);
  box.appendChild(head);
  files.forEach((f, i) => { const l = document.createElement('div'); l.className = f.ok ? 'ok' : 'err'; l.textContent = L.explain(rep.lines[i]); box.appendChild(l); });
  box.hidden = false;
  toast(rep.summary, files.some((f) => !f.ok));
}

function readBase64(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).replace(/^data:[^,]*,/, ''));
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}

async function importFiles(fileList) {
  const files = [];
  for (const f of fileList) files.push({name: f.name, data_base64: await readBase64(f)});
  if (!files.length) return;
  const results = [];
  try {
    for (const batch of L.uploadBatches(files)) {      // only the bytes the user picked, never a path (KP4)
      results.push(...(await (await api('POST', '/api/preset-library/import', {files: batch})).json()).results);
    }
  } catch (e) { toast(e.message, true); }
  if (!results.length) return;
  const rep = L.importReport(results);
  const box = $('#import-result');
  box.innerHTML = '';
  const head = document.createElement('div'); head.className = 'ir-head'; head.textContent = rep.summary;
  const close = document.createElement('button'); close.className = 'icon'; close.textContent = '×'; close.title = '關閉';
  close.onclick = () => { box.hidden = true; };
  head.appendChild(close);
  box.appendChild(head);
  results.forEach((r, i) => { const l = document.createElement('div'); l.className = r.ok ? 'ok' : 'err'; l.textContent = rep.lines[i]; box.appendChild(l); });
  box.hidden = false;
  toast(rep.summary, results.some((r) => !r.ok));
  await reloadLibrary();
}

// "save as preset" reads the edit and never changes it: no dispatch, no undo step (K19)
function refreshSavePreset() {
  $('#save-preset-btn').disabled = !L.canSavePreset(ed);
  capGate($('#save-preset-btn'), capReasonOf('preset_library_writes'));   // S2 E20
}

async function savePreset() {
  if (!L.canSavePreset(ed)) return;
  const name = prompt('自存 preset 的名稱', ed.presetId !== null && st.byId[ed.presetId] ? st.byId[ed.presetId].name : '');
  if (name === null) return;
  const group = prompt('群組（用「 - 」分層）', L.USER_GROUP);
  if (group === null) return;
  if (st.image) await flushSave();
  await flushRetries();                 // S13g''': no failed save is left to land over what follows
  if (st.image && st.edit) {            // PLP6: the photo library's edit (its snapshot) is the source
    // (a photo whose state is only carried over, never changed, has no edit yet: the library flow below, seal F4)
    try {
      const r = await (await api('POST', '/api/edit/save-preset', {path: st.image.path, name, group: group || L.USER_GROUP})).json();
      await reloadLibrary();
      toast(L.presetSaved(r.name));
    } catch (e) { toast(e.message, true); }
    return;
  }
  const req = {preset_id: ed.presetId, strength: strengthNow(), overrides: Object.fromEntries(Object.entries(ed.tweaks).filter(([, d]) => d))};
  await libraryCall('save', L.saveBody(req, name, group), (r) => L.presetSaved(r.name));
}

// ------------------------------------------------------------------ photos
let openSeq = 0;                        // S1: the newest openPhoto wins; older responses are dropped

async function openPhoto(path) {
  path = (path || '').trim().replace(/^"|"$/g, '');
  if (!path) return;
  const token = ++openSeq;              // S1: taken before the flushes, so the newest click wins while a save is sent
  await leaveCrop(true);                // C22 (D10): another photo commits the crop of this one
  await flushSave();                    // the previous photo's last change goes out first (PL15)
  await flushRetries();                 // S13g''': no failed save is left to land over what follows
  if (token !== openSeq) return;
  setStatus('讀取照片中…', 'busy');
  let info;
  try { info = await (await api('POST', '/api/open', {path})).json(); }
  catch (e) { if (token === openSeq) openFailed(path, e.message); return; }
  if (token !== openSeq) return;
  // from here until the saved edit is restored nothing is scheduled for saving (S1): the state is in transit
  st.loading = token;
  st.image = Object.assign(info, {path});
  await dispatch({type: 'carry'}, {restore: true});   // C24 (S11'): the crop is this photo's own, never carried over
  st.snapshots = {}; st.fingerprint = null; st.previous = false; st.editStatus = null;
  $('#photo-path').value = path;
  savePref('lastPath', path);
  $('#photo-size').textContent = `${info.width}×${info.height}`;
  $('#photo-size').title = `預覽 ${info.preview_width}×${info.preview_height}`;
  try { st.folder = await (await api('GET', '/api/folder?image_id=' + info.image_id)).json(); }
  catch (e) { st.folder = null; }
  if (token !== openSeq) return;
  renderPosition();
  refreshExport();
  await loadEdit(path, token);
  if (token !== openSeq) return;
  st.loading = null;
  requestPreview();
}

function openFailed(path, reason) {     // S13 (i): the old picture goes away, the reason is readable
  st.image = null; st.folder = null; st.loading = null;
  applyEditInfo({fingerprint: null, edit: null, preset_status: null, previous: false});
  const img = $('#preview-img'); img.hidden = true; img.removeAttribute('src');
  const empty = $('#preview-empty'); empty.hidden = false;
  empty.textContent = L.openFailed(L.baseName(path), L.explain(reason)); empty.title = reason;
  $('#photo-size').textContent = '';
  renderPosition();
  refreshExport();
  setStatus('預覽：待命');
  toast(L.openFailed(L.baseName(path), L.explain(reason)), true, reason);
}

// ------------------------------------------------------------------ photo library: autosave (PL15 / PLP9)
// The open photo's edit is sent AUTOSAVE_MS after the last change; only the newest state waits (latest wins).
// S1: what is sent (path and body) is fixed when the change is scheduled, never read later from st.image.
// retries: path -> a failed save waiting out its back-off (S13 g / S13g'), one per photo
const save = {timer: null, dirty: false, pending: null, promise: null, retries: new Map()};

function scheduleSave() {
  if (!st.image || st.loading) return;
  if (capReasonOf('photo_library') !== null) return;   // S2 E23: the photo library is off - nothing is saved
  const path = st.image.path;
  save.pending = {path, req: L.editRequest(ed, path, st.snapshots, st.fingerprint), retried: false};
  save.retries.delete(path);            // newer state of this photo supersedes its failed save
  save.dirty = true;
  clearTimeout(save.timer);
  save.timer = setTimeout(flushSave, L.AUTOSAVE_MS);
}

async function sendSave(job) {
  const {path, req} = job;
  try {
    let res;
    if (req.method === 'PASTE') {       // S2: the remembered snapshot goes back as it is (PL8), then re-read
      const r = await (await api('POST', '/api/edit/paste', req.body, {keepalive: true})).json();
      const bad = r.results.find((x) => !x.ok);
      if (bad) throw new Error(bad.error);
      res = await (await api('GET', '/api/edit?path=' + encodeURIComponent(path))).json();
    } else {
      const body = req.body;
      // keepalive: a save sent from beforeunload survives the page going away (seal F3)
      res = await (await api('PUT', '/api/edit', body, {keepalive: true})).json();
    }
    if (st.image && st.image.path === path) applyEditInfo(res);
  } catch (e) {
    toast(L.saveEditFailed(L.explain(e.message)), true, e.message);
    if (!job.retried) {                 // S13 (g): one more try after a short back-off, latest state wins
      // dirty again at once: a page closed during the back-off still sends this body from beforeunload
      // (kept apart from save.pending, so a flush already looping does not resend it before the back-off)
      save.retries.set(path, Object.assign({}, job, {retried: true})); save.dirty = true;
      setTimeout(() => flushRetry(path), L.SAVE_RETRY_MS);
    }
  }
}

async function flushSave() {            // sends what is pending and waits until nothing is in flight
  clearTimeout(save.timer); save.timer = null;
  while (save.pending || save.promise) {
    if (save.promise) { await save.promise; continue; }
    const job = save.pending; save.pending = null; save.dirty = false;
    if (save.retries.size) save.dirty = true;   // a failed save still waits for its retry: unload must send it
    save.promise = sendSave(job).finally(() => { save.promise = null; });
  }
}

async function flushRetry(path) {       // S13g': the one retry of a failed save (after its back-off, or now)
  const r = save.retries.get(path);
  if (!r) return;
  const due = L.retryDue(save.pending && save.pending.path, path);
  if (due === 'superseded') { save.retries.delete(path); return; }
  if (due === 'after') await flushSave();          // another photo's pending save goes first
  if (save.retries.get(path) !== r) return;          // superseded (or sent) meanwhile
  save.retries.delete(path);
  if (save.pending && save.pending.path === path) return;
  save.pending = r;
  await flushSave();
}

async function flushRetries() {         // before another photo is opened: nothing of a failed save is left behind
  for (const path of [...save.retries.keys()]) await flushRetry(path);
  await flushSave();                    // a retry another caller already took may still be in flight: wait it out
}

function unloadSave() {                 // S13 (g): the newest body goes out at once, not after the one in flight
  const jobs = L.unloadJobs(save.pending, [...save.retries.values()]);   // failed saves in back-off go out too
  save.pending = null; save.retries.clear(); save.dirty = false;
  for (const job of jobs) sendSave(job);
}

function applyEditInfo(res) {           // {fingerprint, edit, preset_status, previous} from the photo library
  st.edit = res.edit;
  st.fingerprint = res.fingerprint || null;
  st.previous = !!res.previous;
  st.editStatus = res.preset_status || null;
  if (res.edit && res.edit.preset) st.snapshots[res.edit.preset.id] = res.edit.preset;   // S2: remembered
  const s = $('#edit-status'), text = L.presetStatusText(res.preset_status);
  s.textContent = text; s.title = text; s.hidden = !text;
  renderHint();
  refreshCopy();
  refreshRestorePrevious();
}

function restore(res) {                 // a saved edit comes back: through the reducer, never scheduling a save
  applyEditInfo(res);
  if (!res.edit) return;
  dispatch({type: 'restoreEdit', edit: res.edit}, {restore: true});
}

async function loadEdit(path, token) {  // after opening: restore the saved edit, else keep today's state (R5)
  if (capReasonOf('photo_library') !== null) { applyEditInfo({edit: null, preset_status: null}); return; }   // S2 E23
  let res;
  try { res = await (await api('GET', '/api/edit?path=' + encodeURIComponent(path))).json(); }
  catch (e) {
    if (!st.image || st.image.path !== path) return;
    applyEditInfo({edit: null, preset_status: null}); toast(L.loadEditFailed(L.explain(e.message)), true, e.message);
    return;
  }
  if (!st.image || st.image.path !== path || (token !== undefined && token !== openSeq)) return;   // S1
  restore(res);
}

// ------------------------------------------------------------------ photo library: the grid (PL15 / PLP9)
const gridIO = typeof IntersectionObserver === 'function'
  ? new IntersectionObserver((entries) => { for (const e of entries) if (e.isIntersecting) loadThumb(e.target); }, {rootMargin: '200px'})
  : null;

async function showGrid(on) {
  if (on) await leaveCrop(true);        // C22 (D10): opening the grid commits the crop
  document.body.classList.toggle('grid-open', on);
  $('#grid').hidden = !on;
  $('#grid-btn').setAttribute('aria-pressed', String(on));
  if (!on) return;
  if (st.grid.folder !== null) return;    // S13 (f): a folder the user loaded by hand stays, with its selection
  const folder = st.image ? st.image.path.replace(/[\\/][^\\/]*$/, '') : $('#grid-path').value;
  if (folder && !$('#grid-path').value) $('#grid-path').value = folder;
  if (folder) loadGrid(folder);
}

async function loadGrid(folder) {
  folder = (folder || '').trim().replace(/^"|"$/g, '');
  if (!folder) return;
  let res;
  try { res = await (await api('GET', '/api/folder/thumbnails?folder=' + encodeURIComponent(folder))).json(); }
  catch (e) { toast(L.loadFolderFailed(L.explain(e.message)), true, e.message); return; }
  const keep = st.grid.folder === res.folder ? st.grid : null;       // S9: a re-read keeps the filter and selection
  st.grid = {folder: res.folder, items: res.items, sel: keep ? keep.sel : new Set(), anchor: keep ? keep.anchor : 0,
             filter: st.grid.filter || 'all'};
  $('#grid-path').value = res.folder;
  renderGrid();
}

async function setGridFilter(filter) {   // S9: re-read the listing (fingerprints land in the background), then show
  if (!L.FILTERS.includes(filter)) return;
  st.grid.filter = filter;
  for (const b of document.querySelectorAll('#grid-filter button')) b.setAttribute('aria-pressed', String(b.dataset.filter === filter));
  if (st.grid.folder) await loadGrid(st.grid.folder); else renderGrid();
}

function releaseGrid(box) {             // S13 (e): nothing of the old grid stays behind
  for (const cell of box.querySelectorAll('.cell')) {
    if (gridIO) gridIO.unobserve(cell);
    const img = cell.querySelector('img');
    if (img && img.src.startsWith('blob:')) URL.revokeObjectURL(img.src);
  }
  box.innerHTML = '';
}

function renderGrid() {
  const box = $('#grid-cells');
  releaseGrid(box);
  if (!st.grid.items.length) {           // S13 (j)
    const e = document.createElement('div'); e.className = 'grid-empty'; e.textContent = L.GRID_EMPTY;
    box.appendChild(e);
  }
  const {shown, pending} = L.gridFilter(st.grid.items, st.grid.filter);   // S9
  const shownSet = new Set(shown.map(([i]) => i));
  st.grid.shown = shownSet;
  st.grid.sel = L.onlyShown(st.grid.sel, shownSet);   // selection only among what is shown
  $('#grid-pending').textContent = pending ? L.gridPending(pending) : '';
  $('#grid-pending').hidden = !pending;
  shown.forEach(([i, it], k) => {
    const cell = document.createElement('div');
    cell.className = 'cell' + (it.edited ? ' edited' : '');
    cell.dataset.path = it.path; cell.dataset.i = String(i); cell.tabIndex = k ? -1 : 0;
    cell.setAttribute('role', 'option');
    cell.innerHTML = '<div class="pic"></div><span class="mark" aria-hidden="true"></span><span class="nm"></span>';
    cell.querySelector('.nm').textContent = it.name;
    cell.title = it.path;
    cell.onclick = (e) => selectCell(i, {ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey});
    cell.ondblclick = () => openFromGrid(it.path);
    cell.onkeydown = (e) => {
      if (e.key === 'Enter') { e.preventDefault(); openFromGrid(it.path); }
      else if (e.key === ' ') { e.preventDefault(); selectCell(i, {ctrl: true}); }
      else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        const n = cell[e.key === 'ArrowRight' ? 'nextElementSibling' : 'previousElementSibling'];
        if (n && n.classList.contains('cell')) { e.preventDefault(); n.focus(); }
      }
    };
    box.appendChild(cell);
    if (gridIO) gridIO.observe(cell); else loadThumb(cell);
  });
  renderGridSelection();
}

async function loadThumb(cell) {        // only once the cell is visible; the bytes come through api() (PLP11)
  if (cell.dataset.loaded) return;
  cell.dataset.loaded = '1';
  const pic = cell.querySelector('.pic');
  try {
    const r = await api('GET', '/api/thumbnail?path=' + encodeURIComponent(cell.dataset.path));
    const edited = r.headers.get('X-Edited') === '1';
    cell.classList.toggle('edited', edited);
    const it = st.grid.items[+cell.dataset.i];
    if (it) it.edited = edited;
    let info = null;                     // S8: the badge says which preset, how strong, and whether it is stale
    try { info = r.headers.get('X-Edit') ? JSON.parse(decodeURIComponent(r.headers.get('X-Edit'))) : null; } catch (e) { info = null; }
    cell.classList.toggle('stale', edited && L.stale(info));
    cell.querySelector('.mark').title = edited ? L.badgeTitle(info) : '';
    cell.title = edited ? `${cell.dataset.path}\n${L.badgeTitle(info)}` : cell.dataset.path;
    const img = document.createElement('img');
    img.alt = '';
    const url = URL.createObjectURL(await r.blob());
    img.onload = () => URL.revokeObjectURL(url);     // decoded: the blob's bytes are freed (S13 e)
    img.src = url;
    pic.innerHTML = ''; pic.appendChild(img);
  } catch (e) {
    cell.classList.add('missing');
    pic.textContent = cell.querySelector('.nm').textContent;
    pic.title = L.explain(e.message);
  }
}

function selectCell(i, mods) {
  const r = L.gridSelect(st.grid.sel, i, mods, st.grid.anchor);
  st.grid.sel = L.onlyShown(r.sel, st.grid.shown); st.grid.anchor = r.anchor;   // S9: only what is shown
  renderGridSelection();
}

function renderGridSelection() {
  const cells = $('#grid-cells').querySelectorAll('.cell');
  for (const c of cells) c.classList.toggle('selected', st.grid.sel.has(+c.dataset.i));
  $('#grid-count').textContent = L.gridCount(st.grid.sel.size, cells.length);   // S9: m = what is shown
  refreshCopy();
}

async function openFromGrid(path) {
  await openPhoto(path);
  showGrid(false);
}

const selectedPaths = () => [...st.grid.sel].sort((a, b) => a - b).map((i) => st.grid.items[i].path);

function refreshCopy() {                // copy needs the open photo's edit; paste needs a clipboard and a selection
  $('#copy-edit-btn').disabled = !st.edit;
  $('#paste-edit-btn').disabled = !(st.clipboard && st.grid.sel.size > 0);
  $('#export-selected-btn').disabled = !(st.grid.sel.size > 0);
  $('#grid-reset-original-btn').disabled = !(st.grid.sel.size > 0);     // S10
  $('#grid-restore-btn').disabled = !(st.grid.sel.size > 0);
  const off = capReasonOf('photo_library');                      // S2 E23: the grid's edit buttons are off
  for (const id of ['#copy-edit-btn', '#paste-edit-btn', '#grid-reset-original-btn', '#grid-restore-btn', '#export-selected-btn']) capGate($(id), off);
}

// S10: reset to original / bring back the previous edit, for the selected photos (one request each, in order)
async function gridEach(method, url, targets, summaryFn, cls) {
  const results = [];
  for (const p of targets) {
    try {
      const r = await api(method, url + (method === 'DELETE' ? '?path=' + encodeURIComponent(p) : ''),
                          method === 'DELETE' ? undefined : {path: p});
      await r.json();
      results.push({ok: true, target: p});
    } catch (e) { results.push({ok: false, target: p, error: e.message}); }
  }
  gridBatchDone(summaryFn, targets, results);
  markCells(targets, results, cls);
  if (st.image && targets.includes(st.image.path)) await loadEdit(st.image.path);
}

async function gridResetOriginal() {
  const targets = selectedPaths();
  if (!targets.length) return;
  await flushSave();
  await flushRetries();                 // S13g''': no failed save is left to land over what follows
  if (!confirm(L.resetConfirm(targets.length))) return;
  await gridEach('DELETE', '/api/edit', targets, L.resetDone, 'plain');
}

async function gridRestore() {
  const targets = selectedPaths();
  if (!targets.length) return;
  await flushSave();
  await flushRetries();                 // S13g''': no failed save is left to land over what follows
  await gridEach('POST', '/api/edit/restore', targets, L.restoreDone, 'edited');
}

async function resetOriginal() {        // the editor: one undo step; the photo library keeps the cleared edit
  if (!st.image) return;
  await leaveCrop(true);
  const before = ed;
  await dispatch({type: 'resetToOriginal'});
  if (ed !== before) toast(L.RESET_TOAST);
}

async function restorePrevious() {
  if (!st.image || st.edit || !st.previous) return;
  const path = st.image.path;
  await flushSave();
  await flushRetries();                 // S13g''': no failed save is left to land over what follows
  // a retried save just gave this photo an edit, or another photo is being opened: nothing to restore
  if (!st.image || st.image.path !== path || st.loading || st.edit) return;
  try {
    const res = await (await api('POST', '/api/edit/restore', {path})).json();
    if (st.image && st.image.path === path) { restore(res); requestPreview(); toast(L.RESTORE_TOAST); }
  } catch (e) { toast(e.message, true); }
}

function copyEdit() {
  if (!st.edit || !st.image) return;
  st.clipboard = {edit: st.edit, name: L.baseName(st.image.path)};
  toast(L.copied(st.clipboard.name));
  refreshCopy();
}

function showGridResult(summary, lines) {   // S13 (b): every failed item stays readable, not only a count
  const box = $('#grid-result');
  box.innerHTML = '';
  const head = document.createElement('div'); head.className = 'ir-head'; head.textContent = summary;
  const close = document.createElement('button'); close.className = 'icon'; close.textContent = '×'; close.title = '關閉';
  close.onclick = () => { box.hidden = true; };
  head.appendChild(close);
  box.appendChild(head);
  for (const l of lines) { const d = document.createElement('div'); d.className = 'err'; d.textContent = l; box.appendChild(d); }
  box.hidden = !lines.length;
}

function gridBatchDone(summaryFn, targets, results) {   // results: [{ok, target|source, error}] in target order
  const ok = results.filter((r) => r.ok).length;
  const lines = results.map((r, k) => (r.ok ? null : `${L.baseName(targets[k])}：${L.explain(r.error)}`)).filter(Boolean);
  const summary = summaryFn(ok, results.length - ok);
  showGridResult(summary, lines);
  toast(summary, lines.length > 0);
  return ok;
}

function markCells(targets, results, cls) {
  results.forEach((r, k) => {
    if (!r.ok) return;
    const i = st.grid.items.findIndex((it) => it.path === targets[k]);
    const cell = $('#grid-cells').querySelector(`.cell[data-i="${i}"]`);
    if (i >= 0) st.grid.items[i].edited = cls === 'edited';
    if (cell) { cell.classList.toggle('edited', cls === 'edited'); cell.classList.remove('stale'); }
  });
}

async function pasteEdit() {
  const targets = selectedPaths();
  if (!st.clipboard || !targets.length) return;
  await flushSave();                    // S13 (h): the open photo's pending save never races the paste
  await flushRetries();                 // S13g''': no failed save is left to land over what follows
  const withGeometry = $('#paste-geometry').checked;        // C26: off by default, never remembered
  if (!confirm(L.pasteConfirmWith(st.clipboard.name, targets.length, withGeometry))) return;
  let res;
  try { res = await (await api('POST', '/api/edit/paste', {targets, edit: st.clipboard.edit, with_geometry: withGeometry})).json(); }
  catch (e) { toast(e.message, true); return; }
  gridBatchDone(L.pasteDone, targets, res.results);
  markCells(targets, res.results, 'edited');
  if (st.image && targets.includes(st.image.path)) await loadEdit(st.image.path);
}

async function exportSelected(settings) {   // each photo with its own saved edit (E15); settings from the dialog
  const paths = selectedPaths();
  if (!paths.length || exp.busy) return;
  exp.busy = true;                      // S13 (a): a second click must not export everything twice
  const btn = $('#export-selected-btn');
  btn.disabled = true; btn.textContent = L.EXPORT_BUSY;
  refreshDialog();
  try {
    await flushSave();
    await flushRetries();                 // S13g''': no failed save is left to land over what follows
    const lines = [];
    const items = paths.map((p) => ({path: p}));   // S2 E15: only the path - the server uses each photo's saved edit
    let ok = 0, fail = 0;
    if (items.length) {
      const body = L.exportRequest(items, settings || dialogSettings());
      try {
        const res = await (await api('POST', '/api/export', body)).json();
        ok = res.results.filter((r) => r.ok).length;
        fail += res.results.length - ok;
        res.results.forEach((r) => { if (!r.ok) lines.push(`${L.baseName(r.source)}：${L.explain(r.error)}`); });
      } catch (e) { fail += items.length; lines.push(L.explain(e.message)); }
    }
    showGridResult(L.exportSelectedDone(ok, fail), lines);
    toast(L.exportSelectedDone(ok, fail), fail > 0);
  } finally {
    exp.busy = false;
    btn.textContent = '匯出所選';
    refreshCopy();
    refreshExport();
  }
}

// ------------------------------------------------------------------ export (X13): reads the edit, never changes it
const exp = {busy: false};

function refreshExport() {
  const b = $('#export-btn');
  b.disabled = !st.image || exp.busy;
  b.textContent = exp.busy ? L.EXPORT_BUSY : '匯出';
  refreshDialog();                                   // S2 E29: the dialog decides what is disabled in it
  refreshAb();                                       // S7 / C25
  $('#crop-btn').disabled = !st.image;               // C22
  $('#reset-original-btn').disabled = !st.image;     // S10
}

// S2 E15a (seal F1): the open photo is exported exactly as it is shown - its own parameters go with it, never only
// its path, so a save that failed (PLP1, a full disk) can never turn the export into the saved or original photo.
// The save is still flushed first (S11), so the photo library holds what was exported whenever it can.
async function currentExportItems() {
  if (capReasonOf('photo_library') === null) {
    await flushSave();
    await flushRetries();
  }
  return [currentRequest()];
}

async function commitCarried() {        // S11: a carried-over state becomes this photo's edit before it is exported
  if (!st.image || st.edit || !L.carryHintVisible(ed, true, false)) return;
  scheduleSave();
  await flushSave();
}

async function exportPhoto(settings) {   // settings: the dialog's (E29); never a folder over HTTP
  if (!st.image || exp.busy) return;
  exp.busy = true;
  refreshExport();
  const name = L.baseName(st.image.path);
  await commitCarried();
  try {
    const items = await currentExportItems();
    const res = await (await api('POST', '/api/export', L.exportRequest(items, settings || dialogSettings()))).json();
    const r = res.results[0];
    toast(L.exportMessage(r), !r.ok);
  } catch (e) {
    toast(L.exportFailed(name, e.message), true);
  } finally {
    exp.busy = false;
    refreshExport();
  }
}

function renderPosition() {
  const f = st.folder;
  renderHint();
  if (!f || f.index < 0) { $('#position').textContent = st.image ? st.image.path : '尚未開啟照片'; $('#prev').disabled = $('#next').disabled = true; return; }
  $('#position').textContent = `${f.index + 1}/${f.files.length} ${f.files[f.index].name}`;
  $('#position').title = f.files[f.index].path;
  $('#prev').disabled = f.index <= 0;
  $('#next').disabled = f.index >= f.files.length - 1;
}

// ------------------------------------------------------------------ S2 export dialog (E29): opened by both export
// buttons, filled with the last settings; Enter exports, Esc closes. Never changes the edit, never an undo step.
const xd = {target: null, opener: null};
const XD_IDS = ['#xd-preset', '#xd-preset-save', '#xd-preset-delete', '#xd-format', '#xd-bit-depth', '#xd-quality', '#xd-max-kb-on',
                '#xd-max-kb', '#xd-resize-mode', '#xd-resize-value', '#xd-metadata', '#xd-remove-gps', '#xd-sharpen-target',
                '#xd-sharpen-amount', '#xd-cancel', '#xd-go'];

function formValues() {
  return {format: $('#xd-format').value, bit_depth: $('#xd-bit-depth').value, quality: $('#xd-quality').value,
          max_kb_on: $('#xd-max-kb-on').checked, max_kb: $('#xd-max-kb').value, resize_mode: $('#xd-resize-mode').value,
          resize_value: $('#xd-resize-value').value, metadata: $('#xd-metadata').value, remove_gps: $('#xd-remove-gps').checked,
          sharpen_target: $('#xd-sharpen-target').value, sharpen_amount: $('#xd-sharpen-amount').value};
}
const dialogSettings = () => L.settingsFromForm(formValues());

function fillDialog(s) {
  $('#xd-format').value = s.format;
  $('#xd-bit-depth').value = String(s.bit_depth == null ? L.defaultBitDepth(s.format) : s.bit_depth);
  if (s.quality != null) $('#xd-quality').value = String(s.quality);
  $('#xd-max-kb-on').checked = s.max_kb != null;
  if (s.max_kb != null) $('#xd-max-kb').value = String(s.max_kb);
  $('#xd-resize-mode').value = s.resize ? s.resize.mode : '';
  if (s.resize) $('#xd-resize-value').value = String(s.resize.value);
  $('#xd-metadata').value = s.metadata;
  $('#xd-remove-gps').checked = !!s.remove_gps;
  $('#xd-sharpen-target').value = s.sharpen ? s.sharpen.target : '';
  $('#xd-sharpen-amount').value = s.sharpen ? s.sharpen.amount : 'standard';
  refreshDialog();
}

function refreshDialog() {               // every disabled state comes from L.exportDialogState (E29)
  const s = dialogSettings();
  const ds = L.exportDialogState(s, st.caps);
  $('#xd-quality').disabled = ds.quality.disabled;
  $('#xd-bit-depth').disabled = ds.bitDepth.disabled;
  for (const o of $('#xd-bit-depth').options) o.disabled = !ds.bitDepth.options.includes(+o.value);
  if (ds.bitDepth.disabled) $('#xd-bit-depth').value = '8';
  $('#xd-max-kb-on').disabled = ds.maxKbOn.disabled;
  $('#xd-max-kb').disabled = ds.maxKb.disabled;
  const wo = $('#xd-format').querySelector('option[value="webp"]');
  wo.disabled = ds.webp.disabled; wo.title = ds.webp.title;
  const rv = $('#xd-resize-value');
  rv.disabled = ds.resizeValue.disabled; rv.min = String(ds.resizeValue.min); rv.max = String(ds.resizeValue.max); rv.step = String(ds.resizeValue.step);
  $('#xd-remove-gps').disabled = ds.removeGps.disabled;
  $('#xd-sharpen-amount').disabled = ds.sharpenAmount.disabled;
  $('#xd-summary').textContent = L.exportSummary(s);
  const go = $('#xd-go');
  go.disabled = exp.busy || ds.go.disabled;
  go.textContent = exp.busy ? L.EXPORT_BUSY : '匯出';
  go.title = ds.go.disabled ? ds.webp.title : '匯出（Enter）';
  const sel = $('#xd-preset');
  const chosen = st.exportPresets.find((x) => x.name === sel.value);
  if (chosen && !L.sameSettings(chosen.settings, s)) sel.value = '';            // changed by hand: （自訂）
  $('#xd-preset-delete').disabled = !sel.value;
}

function renderExportPresets(select) {
  const sel = $('#xd-preset');
  sel.innerHTML = '';
  const custom = document.createElement('option'); custom.value = ''; custom.textContent = L.CUSTOM_PRESET; sel.appendChild(custom);
  for (const x of st.exportPresets) { const o = document.createElement('option'); o.value = x.name; o.textContent = x.name; sel.appendChild(o); }
  sel.value = st.exportPresets.some((x) => x.name === select) ? select : '';
}

async function loadExportPresets(select) {
  try { st.exportPresets = (await (await api('GET', '/api/export-presets')).json()).presets; }
  catch (e) { st.exportPresets = []; toast(e.message, true); }
  renderExportPresets(select);
  refreshDialog();
}

let toastAct = null;
function toastUndo(msg, undoFn) {        // E29: an updated or deleted export preset can be brought back
  toast(msg);
  const t = $('#toast');
  const b = document.createElement('button'); b.textContent = L.UNDO_LABEL; b.className = 'toast-act';
  b.onclick = async () => { t.className = ''; await undoFn(); };
  t.appendChild(b); t.classList.add('act');
  clearTimeout(toastT); clearTimeout(toastAct);
  toastAct = setTimeout(() => { t.className = ''; }, 6000);
}

async function putExportPreset(name, settings) {   // export presets (data_dir); the edit's PUT stays in sendSave alone
  return (await api('PUT', '/api/export-presets', {name, settings})).json();
}
async function deleteExportPreset(name) {
  return (await api('DELETE', '/api/export-presets?name=' + encodeURIComponent(name))).json();
}

async function saveExportPreset() {
  const name = prompt(L.EXPORT_PRESET_NAME_PROMPT, $('#xd-preset').value || '');
  if (name === null) return;
  let res;
  try { res = await putExportPreset(name, dialogSettings()); } catch (e) { toast(e.message, true); return; }
  await loadExportPresets(res.name);
  fillDialog(L.exportSettingsFrom(res.settings));
  $('#xd-preset').value = res.name; refreshDialog();
  if (res.previous) {
    toastUndo(L.exportPresetUpdated(res.name), async () => {
      try { await putExportPreset(res.name, res.previous); } catch (e) { toast(e.message, true); }
      await loadExportPresets(res.name);
    });
  } else {
    toastUndo(L.exportPresetSaved(res.name), async () => {
      try { await deleteExportPreset(res.name); } catch (e) { toast(e.message, true); }
      await loadExportPresets('');
    });
  }
}

async function removeExportPreset() {
  const name = $('#xd-preset').value;
  if (!name) return;
  let res;
  try { res = await deleteExportPreset(name); } catch (e) { toast(e.message, true); return; }
  await loadExportPresets('');
  toastUndo(L.exportPresetDeleted(res.name), async () => {
    try { await putExportPreset(res.name, res.settings); } catch (e) { toast(e.message, true); }
    await loadExportPresets(res.name);
  });
}

async function openExportDialog(target) {
  await leaveCrop(true);                // C22 (D10): the export dialog commits the crop first (E15a sends it)
  if (target === 'photo' ? !st.image : !st.grid.sel.size) return;
  xd.target = target; xd.opener = document.activeElement;
  let stored = null;
  try { stored = localStorage.getItem(L.EXPORT_SETTINGS_KEY); } catch (e) { stored = null; }
  fillDialog(L.exportSettingsFrom(stored));
  $('#xd-target').textContent = target === 'photo' ? L.baseName(st.image.path) : L.gridCount(st.grid.sel.size, st.grid.items.length);
  $('#export-backdrop').hidden = false;
  loadExportPresets('');
  $('#xd-go').focus();
}

function closeExportDialog() {
  if ($('#export-backdrop').hidden) return;
  $('#export-backdrop').hidden = true;
  if (xd.opener && xd.opener.focus) xd.opener.focus();
}

async function runExport() {
  if (exp.busy || $('#xd-go').disabled) return;
  const settings = dialogSettings();
  try { localStorage.setItem(L.EXPORT_SETTINGS_KEY, JSON.stringify(settings)); } catch (e) { /* optional */ }
  if (xd.target === 'selected') await exportSelected(settings); else await exportPhoto(settings);
  closeExportDialog();
}

function initExportDialog() {
  $('#export-dialog').addEventListener('submit', (e) => { e.preventDefault(); runExport(); });
  $('#export-dialog').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); closeExportDialog(); return; }
    if (e.key === 'Enter' && !(e.target.matches && e.target.matches('button, input[type=checkbox]'))) { e.preventDefault(); runExport(); return; }
    if (e.key === 'Tab') {               // aria-modal: focus stays inside the dialog
      const f = XD_IDS.map((id) => $(id)).filter((el) => !el.disabled);
      const i = f.indexOf(document.activeElement);
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
    }
  });
  $('#export-backdrop').addEventListener('click', (e) => { if (e.target === $('#export-backdrop')) closeExportDialog(); });
  $('#xd-cancel').onclick = closeExportDialog;
  $('#xd-format').addEventListener('change', () => { $('#xd-bit-depth').value = String(L.defaultBitDepth($('#xd-format').value)); refreshDialog(); });
  for (const id of ['#xd-bit-depth', '#xd-quality', '#xd-max-kb-on', '#xd-max-kb', '#xd-resize-mode', '#xd-resize-value', '#xd-metadata',
                    '#xd-remove-gps', '#xd-sharpen-target', '#xd-sharpen-amount']) {
    $(id).addEventListener('input', refreshDialog);
    $(id).addEventListener('change', refreshDialog);
  }
  $('#xd-preset').addEventListener('change', () => {
    const x = st.exportPresets.find((p) => p.name === $('#xd-preset').value);
    if (x) { fillDialog(L.exportSettingsFrom(x.settings)); $('#xd-preset').value = x.name; }
    refreshDialog();
  });
  $('#xd-preset-save').onclick = saveExportPreset;
  $('#xd-preset-delete').onclick = removeExportPreset;
}

function step(delta) {
  const f = st.folder;
  if (!f || f.index < 0) return;
  const i = f.index + delta;
  if (i < 0 || i >= f.files.length) return;   // first / last photo: nothing happens
  openPhoto(f.files[i].path);
}

// ------------------------------------------------------------------ columns (R6 narrow windows)
function toggleLib() {
  if (NARROW.matches) document.body.classList.toggle('lib-open');
  else document.body.classList.toggle('lib-collapsed');
}

// ------------------------------------------------------------------ S3 crop mode (CONTRACT-s3-crop C22-C25): the draft
// lives in L.cropSession, never in the reducer; the screen shows the whole straightened frame (frame preview) with
// the box over it. Dragging the box never asks the backend for anything; only rotate / flip / straighten change the
// frame picture. Commit (Enter, 完成, 裁切 / R again, another photo, the grid, the export dialog) = one setGeometry
// step; cancel (Esc, 取消) = nothing happened.
const crop = {s: null, drag: null};
const cropActive = () => !!(crop.s && crop.s.active);
const photoSize = () => ({width: st.image.width, height: st.image.height});

function frameRequest() {              // the crop mode's picture: the whole frame of the draft (its crop ignored)
  const d = Object.assign({}, crop.s.draft, {crop: null});
  return Object.assign(currentRequest(), {geometry: L.normGeometry(d), frame: true});
}
const frameKey = (g) => JSON.stringify([g.rotate, g.flip, g.angle]);

function enterCrop() {
  if (!st.image || cropActive() || st.loading) return;
  if (ab.on) abToggle(false);          // C25: A/B is off in the crop mode, and stays off after it
  crop.s = L.cropSession(null, {type: 'enter', geometry: ed.geometry});
  $('#crop-panel').hidden = false;
  $('#crop-btn').setAttribute('aria-pressed', 'true');
  $('#preview').classList.add('cropping');
  refreshAb();
  renderCropControls();
  requestPreview();
}

async function leaveCrop(commit) {      // C22 (D10): only Esc / 取消 cancel; every other way out commits
  if (!cropActive()) return;
  const s = L.cropSession(crop.s, commit ? Object.assign({type: 'commit'}, photoSize()) : {type: 'cancel'});
  crop.s = null; crop.drag = null;
  $('#crop-panel').hidden = true;
  $('#crop-box').hidden = true;
  $('#crop-btn').setAttribute('aria-pressed', 'false');
  $('#preview').classList.remove('cropping');
  refreshAb();
  if (commit && s.result.changed) await dispatch({type: 'setGeometry', geometry: s.result.geometry});   // one step
  else requestPreview();
}

function cropChange(draft, gesture) {
  const before = frameKey(crop.s.draft);
  crop.s = L.cropSession(crop.s, {type: 'change', draft, gesture});
  renderCropControls();
  layoutCrop();
  if (frameKey(crop.s.draft) !== before) requestPreview();   // straighten / rotate / flip: a new frame picture
}

function cropStep(type) {               // the draft's own undo / redo / reset (Ctrl+Z only moves the draft)
  const before = frameKey(crop.s.draft);
  crop.s = L.cropSession(crop.s, {type});
  renderCropControls();
  layoutCrop();
  if (frameKey(crop.s.draft) !== before) requestPreview();
}

function geometryAct(action) {          // rotate / flip / orientation: in the crop mode the draft, else one step
  if (!st.image) return;
  const {width, height} = photoSize();
  if (cropActive()) { cropChange(L.geometryAction(crop.s.draft, action, width, height)); return; }
  dispatch({type: 'setGeometry', geometry: L.geometryAction(ed.geometry, action, width, height)});
}

function renderCropControls() {
  if (!cropActive()) return;
  const d = crop.s.draft, {width, height} = photoSize();
  const orient = L.cropOrientation(d, width, height);
  const sel = $('#crop-aspect');
  sel.innerHTML = '';
  for (const [v, label] of L.aspectOptions(orient === 'landscape')) {
    const o = document.createElement('option'); o.value = v; o.textContent = label; sel.appendChild(o);
  }
  if (![...sel.options].some((o) => o.value === d.aspect)) {   // a ratio typed by an agent: shown as it is
    const o = document.createElement('option'); o.value = d.aspect; o.textContent = d.aspect; sel.appendChild(o);
  }
  sel.value = d.aspect;
  const ob = $('#crop-orient');
  ob.disabled = d.aspect === 'free' || d.aspect === '1:1';
  ob.textContent = orient === 'portrait' ? L.ORIENT_LANDSCAPE : L.ORIENT_PORTRAIT;   // what pressing it gives
  if (document.activeElement !== $('#crop-angle')) $('#crop-angle').value = String(d.angle);
  if (document.activeElement !== $('#crop-angle-num')) $('#crop-angle-num').value = String(d.angle);
  $('#crop-hint').textContent = L.CROP_HINT;
}

function layoutCrop() {                 // the box over the frame picture (only once the frame picture is shown)
  const box = $('#crop-box'), img = $('#preview-img');
  if (!cropActive() || img.hidden || img.dataset.kind !== 'frame') { box.hidden = true; return; }
  const {width, height} = photoSize();
  const b = L.fitCrop(crop.s.draft, width, height).box;
  const l = img.offsetLeft, t = img.offsetTop, w = img.offsetWidth, h = img.offsetHeight;
  Object.assign(box.style, {left: (l + b[0] * w) + 'px', top: (t + b[1] * h) + 'px',
                            width: ((b[2] - b[0]) * w) + 'px', height: ((b[3] - b[1]) * h) + 'px'});
  box.hidden = false;
}

function initCrop() {
  $('#crop-btn').onclick = () => (cropActive() ? leaveCrop(true) : enterCrop());
  $('#crop-done').onclick = () => leaveCrop(true);
  $('#crop-cancel').onclick = () => leaveCrop(false);
  $('#crop-reset').onclick = () => cropStep('reset');
  $('#rotate-left').onclick = () => geometryAct('rotate_left');
  $('#rotate-right').onclick = () => geometryAct('rotate_right');
  $('#flip-h').onclick = () => geometryAct('flip_h');
  $('#flip-v').onclick = () => geometryAct('flip_v');
  $('#crop-orient').onclick = () => geometryAct('orient');
  $('#crop-aspect').addEventListener('change', () => {
    if (!cropActive()) return;
    const {width, height} = photoSize();
    const d = Object.assign(L.fullGeometry(crop.s.draft), {aspect: $('#crop-aspect').value});
    if (d.crop) d.crop = Object.fromEntries(L.CROP_EDGES.map((k, i) => [k, L.fitCrop(d, width, height).box[i]]));
    cropChange(d);
  });
  const angle = (v, gesture) => {       // straighten: the latest frame preview wins (B7), the box fits itself in
    if (!cropActive() || !Number.isFinite(v)) return;
    const a = Math.round(Math.min(45, Math.max(-45, v)) / L.ANGLE_STEP) * L.ANGLE_STEP;
    cropChange(Object.assign(L.fullGeometry(crop.s.draft), {angle: Math.round(a * 10) / 10}), gesture);
  };
  $('#crop-angle').addEventListener('input', () => angle(+$('#crop-angle').value, 'angle'));
  $('#crop-angle').addEventListener('change', () => { if (cropActive()) crop.s = L.cropSession(crop.s, {type: 'endGesture'}); });
  $('#crop-angle').addEventListener('dblclick', () => angle(0));
  $('#crop-angle-num').addEventListener('change', () => angle(parseFloat($('#crop-angle-num').value)));
  const box = $('#crop-box');
  box.addEventListener('pointerdown', (e) => {          // C23: the box and its 8 handles; no preview while dragging
    if (!cropActive()) return;
    e.preventDefault();
    box.setPointerCapture(e.pointerId);
    const img = $('#preview-img');
    crop.drag = {handle: e.target.dataset && e.target.dataset.h ? e.target.dataset.h : 'move', x: e.clientX, y: e.clientY,
                 start: crop.s.draft, w: img.offsetWidth, h: img.offsetHeight};
    box.classList.add('dragging');
  });
  box.addEventListener('pointermove', (e) => {
    const g = crop.drag;
    if (!g || !cropActive()) return;
    const size = Object.assign(photoSize(), {minW: L.CROP_MIN_PX / g.w, minH: L.CROP_MIN_PX / g.h});
    cropChange(L.cropDrag(g.start, size, g.handle, (e.clientX - g.x) / g.w, (e.clientY - g.y) / g.h), 'drag');
  });
  const up = () => {
    if (!crop.drag) return;
    crop.drag = null;
    box.classList.remove('dragging');
    if (cropActive()) crop.s = L.cropSession(crop.s, {type: 'endGesture'});
  };
  box.addEventListener('pointerup', up);
  box.addEventListener('pointercancel', up);
  box.addEventListener('keydown', (e) => {               // the focused box: arrows 0.5 %, Shift 5 %
    const mv = L.cropKeyMove(e.key, e.shiftKey);
    if (!mv || !cropActive()) return;
    e.preventDefault(); e.stopPropagation();
    const img = $('#preview-img');
    const size = Object.assign(photoSize(), {minW: L.CROP_MIN_PX / img.offsetWidth, minH: L.CROP_MIN_PX / img.offsetHeight});
    cropChange(L.cropDrag(crop.s.draft, size, 'move', mv[0], mv[1]));
  });
  if (typeof ResizeObserver === 'function') new ResizeObserver(layoutCrop).observe($('#preview'));
  $('#preview-img').addEventListener('load', layoutCrop);
}

function cropKey(e) {                   // the keyboard while cropping; true when the key was ours
  const k = e.key.toLowerCase();
  if (e.key === 'Escape') { e.preventDefault(); leaveCrop(false); return true; }
  if (e.key === 'Enter' && !(e.target.matches && e.target.matches('button, select, input'))) {
    e.preventDefault(); leaveCrop(true); return true;
  }
  if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); cropStep(e.shiftKey ? 'redo' : 'undo'); return true; }
  if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); cropStep('redo'); return true; }
  if (typing(e.target)) return false;
  if (k === 'x' && !e.ctrlKey && !e.metaKey && !e.altKey && !$('#crop-orient').disabled) { geometryAct('orient'); return true; }
  if (k === L.AB_KEY) return true;      // C25: no A/B while cropping
  return false;
}

// ------------------------------------------------------------------ wiring
const typing = (el) => !!(el && el.matches && (el.matches('input[type=text], input[type=search], input[type=number]') || el.isContentEditable));
const inField = (el) => !!(el && el.matches && el.matches('input, select, textarea'));   // S13 (c): arrows stay there

async function init() {
  $('#open-form').addEventListener('submit', (e) => { e.preventDefault(); openPhoto($('#photo-path').value); });
  $('#prev').onclick = () => step(-1);
  $('#next').onclick = () => step(1);
  $('#undo').onclick = undo;
  $('#redo').onclick = redo;
  $('#toggle-lib').onclick = toggleLib;
  $('#toggle-sl').onclick = () => document.body.classList.toggle('sl-collapsed');
  $('#strength').addEventListener('input', () => setStrength(+$('#strength').value, 'strength'));
  $('#strength').addEventListener('change', () => dispatch({type: 'endGesture'}));
  $('#strength-100').onclick = () => setStrength(100);
  $('#strength-value').addEventListener('dblclick', () => {
    if (!L.strengthEnabled(ed)) return;
    editValue($('#strength-value'), String(ed.strength), STRENGTH, (v) => setStrength(v));
    const inp = $('#strength-value input');
    if (inp) inp.addEventListener('blur', () => setTimeout(renderStrength, 0), {once: true});
  });
  setCanvas(loadPref('canvas', 'dark'));                                         // S17
  for (const b of document.querySelectorAll('.canvas-pick button')) b.onclick = () => setCanvas(b.dataset.canvas);
  $('#reset-all').onclick = () => dispatch({type: 'resetAll'});
  $('#reset-original-btn').onclick = resetOriginal;          // S10
  $('#restore-previous-btn').onclick = restorePrevious;
  $('#grid-reset-original-btn').onclick = gridResetOriginal;
  $('#grid-restore-btn').onclick = gridRestore;
  for (const b of document.querySelectorAll('#grid-filter button')) b.onclick = () => setGridFilter(b.dataset.filter);   // S9
  initCompare();                                             // S7
  initCrop();                                                // S3 C22
  $('#export-btn').onclick = () => openExportDialog('photo');   // S2 E29 (D3): always the dialog, Enter exports
  initExportDialog();
  $('#cap-btn').onclick = (e) => { e.stopPropagation(); toggleCapDetail(); };   // S2 E30
  $('#cap-refresh').onclick = () => loadCaps(true);
  document.addEventListener('click', (e) => { if (!e.target.closest('#cap-detail') && !e.target.closest('#cap-btn')) toggleCapDetail(false); });
  $('#save-preset-btn').onclick = savePreset;
  $('#import-btn').onclick = () => $('#import-file').click();
  $('#import-file').addEventListener('change', (e) => { const fl = [...e.target.files]; e.target.value = ''; importFiles(fl); });
  $('#new-group-btn').onclick = () => askNewGroup('');
  document.addEventListener('click', (e) => { if (!e.target.closest('.menu-pop')) closeMenu(); });
  refreshExport();
  for (const id of ['#skip-banner', '#skip-note']) {       // S12
    $(id).addEventListener('click', () => toggleSkipDetail());
    $(id).addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSkipDetail(); } });
  }
  $('#skip-detail').addEventListener('click', () => toggleSkipDetail(false));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#skip-detail').hidden) toggleSkipDetail(false); });
  $('#grid-btn').onclick = () => showGrid(!document.body.classList.contains('grid-open'));
  $('#grid-load').onclick = () => loadGrid($('#grid-path').value);
  $('#grid-path').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); loadGrid($('#grid-path').value); } });
  $('#copy-edit-btn').onclick = copyEdit;
  $('#paste-edit-btn').onclick = pasteEdit;
  $('#export-selected-btn').onclick = () => openExportDialog('selected');   // S2 E29
  window.addEventListener('beforeunload', () => { if (save.dirty) unloadSave(); });
  refreshCopy();
  $('#search').addEventListener('input', (e) => { st.search = e.target.value.trim(); renderTree(); });
  $('#preset-tree').addEventListener('keydown', onTreeKey);
  const hold = $('#hold');
  hold.addEventListener('pointerdown', () => showOriginal(true));
  for (const ev of ['pointerup', 'pointerleave']) hold.addEventListener(ev, () => { if (st.holding) showOriginal(false); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#cap-detail').hidden) { toggleCapDetail(false); $('#cap-btn').focus(); return; }
    if (!$('#export-backdrop').hidden) return;          // S2 E29: the dialog has the keyboard
    if (cropActive() && cropKey(e)) return;              // S3 C22: Enter / Esc / Ctrl+Z / X while cropping
    if (typing(e.target)) return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && (e.key === '[' || e.key === ']')) {   // C23: rotate 90°, in or out of the crop mode
      e.preventDefault(); geometryAct(e.key === '[' ? 'rotate_left' : 'rotate_right'); return;
    }
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); redo(); return; }
    if (e.target.closest && (e.target.closest('#preset-tree') || e.target.closest('#grid'))) return;
    if (k === L.AB_KEY && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey && !e.repeat) { abToggle(); return; }   // S7
    if (k === 'r' && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey && !e.repeat) {   // C22: R = 裁切
      if (cropActive()) leaveCrop(true); else enterCrop();
      return;
    }
    if (e.key === '\\' && !e.repeat) showOriginal(true);
    else if (e.key === 'ArrowLeft' && !inField(e.target) && !e.repeat) step(-1);
    else if (e.key === 'ArrowRight' && !inField(e.target) && !e.repeat) step(1);
  });
  document.addEventListener('keyup', (e) => { if (e.key === '\\' && st.holding) showOriginal(false); });
  // S13 (d): a window that loses focus never gets the keyup; the original must not stay stuck on screen
  window.addEventListener('blur', () => { if (st.holding) showOriginal(false); });
  document.addEventListener('visibilitychange', () => { if (document.hidden && st.holding) showOriginal(false); });

  const [presets, sl, flags, groups] = await Promise.all([
    api('GET', '/api/presets').then((r) => r.json()),
    api('GET', '/api/sliders').then((r) => r.json()),
    api('GET', '/api/preset_flags').then((r) => r.json()),
    api('GET', '/api/preset-library/groups').then((r) => r.json()),
  ]);
  st.presets = presets; st.flags = flags; st.libGroups = groups;
  presets.forEach((p) => { st.byId[p.id] = p; });
  st.sliders = sl.sliders; st.groups = sl.groups;
  sl.sliders.forEach((s) => { st.byKey[s.key] = s; });
  renderTree();
  renderStrength();
  renderSliders();
  refreshUndo();
  refreshSavePreset();
  loadCaps(false);                      // S2 E22: after the page is ready; never waited for
  // S15: ?path= only fills the box (a link from outside the browser must not make the app read a path);
  // the last opened photo is restored as before
  const q = new URLSearchParams(location.search).get('path');
  const last = loadPref('lastPath', '');
  if (q) $('#photo-path').value = q;
  else if (last) { $('#photo-path').value = last; openPhoto(last); }
}

window.darkroom = {st, pv, ab, get ed() { return ed; }, dispatch, requestPreview, selectPreset, openPhoto, step, undo, redo, setStrength,
                   exportPhoto, savePreset, importFiles, reloadLibrary,
                   flushSave, loadEdit, showGrid, loadGrid, copyEdit, pasteEdit, exportSelected,
                   abToggle, abSetSplit, setGridFilter, resetOriginal, restorePrevious, gridResetOriginal, gridRestore,
                   openExportDialog, closeExportDialog, runExport, loadCaps, downloadPresets, loadExportPresets,
                   crop, enterCrop, leaveCrop, geometryAct};
init().catch((e) => toast('載入失敗：' + e.message, true));
