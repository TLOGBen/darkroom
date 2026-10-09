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
  grid: {folder: null, items: [], sel: new Set(), anchor: 0},   // the thumbnail grid (PLP9)
  search: '', openFolders: {'\u0001fav': true}, openGroups: loadPref('openGroups', {basic: true}), hslTab: 'h', focusKey: null,
  holding: false, originalUrl: null, originalFor: null,
};
let ed = L.initialEditor();   // {presetId, strength, tweaks, past, future, gesture}

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
function refreshRestorePrevious() { $('#restore-previous-btn').disabled = !(st.image && !st.edit && st.previous); }   // S10

async function dispatch(action, opts) {
  const prev = ed;
  ed = L.reduce(ed, action);
  if (ed === prev) return;
  refreshUndo();
  renderHint();
  refreshSavePreset();
  const sameState = prev.presetId === ed.presetId && prev.strength === ed.strength &&
    JSON.stringify(prev.tweaks) === JSON.stringify(ed.tweaks);
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
const undo = () => dispatch({type: 'undo'});
const redo = () => dispatch({type: 'redo'});

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

function currentRequest() {
  const overrides = {};
  for (const [k, d] of Object.entries(ed.tweaks)) if (d) overrides[k] = d;
  return {image_id: st.image.image_id, preset_id: ed.presetId, strength: strengthNow(), overrides};
}

function requestPreview() {
  if (!st.image) return;
  pv.pending = {body: currentRequest(), seq: ++pv.seq};
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
      try { r = await api('POST', '/api/preview', job.body); } catch (e) { setStatus('預覽失敗：' + e.message, 'err'); continue; }
      const ms = r.headers.get('X-Render-Ms');
      const blob = await r.blob();
      if (job.seq < pv.shownSeq) continue;
      pv.shownSeq = job.seq;
      const url = URL.createObjectURL(blob);
      if (!st.holding) await swapImage($('#preview-img'), url);
      if (pv.url) URL.revokeObjectURL(pv.url);
      pv.url = url;
      if (!pv.pending) {
        const rt = performance.now() - t0;
        setStatus('預覽：已更新', 'mute', `後端 ${(+ms).toFixed(0)} ms，往返 ${rt.toFixed(0)} ms`);
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

async function showOriginal(on) {
  if (!st.image) return;
  st.holding = on;
  $('#pv-label').hidden = !on;
  $('#hold').classList.toggle('on', on);
  const img = $('#preview-img');
  if (!on) { if (pv.url) img.src = pv.url; return; }
  if (st.originalFor !== st.image.image_id) {
    const r = await api('POST', '/api/preview', {image_id: st.image.image_id, preset_id: null, strength: 100, overrides: {}});
    if (st.originalUrl) URL.revokeObjectURL(st.originalUrl);
    st.originalUrl = URL.createObjectURL(await r.blob());
    st.originalFor = st.image.image_id;
  }
  if (st.holding) img.src = st.originalUrl;
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
  el.title = p.group ? p.group + ' / ' + p.name : p.name;
  el.querySelector('.fav').onclick = (e) => { e.stopPropagation(); toggleFavorite(p); };
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
  const inp = row.querySelector('input[type=range]');
  if (document.activeElement !== inp || !row.dragging) inp.value = v.value;
  const vs = row.querySelector('.v');
  if (!vs.querySelector('input')) vs.textContent = L.fmtNum(s, v.value);
  row.querySelector('.cn').textContent = L.clampNote(v);
  row.title = L.sliderTooltip(s, presetValue(key), strengthNow(), ed.tweaks[key] || 0);
}

function sliderRow(s) {
  const row = document.createElement('div');
  row.className = 'sl';
  row.dataset.key = s.key;
  row.innerHTML = `<label></label><input type="range" min="${s.min}" max="${s.max}" step="${s.step}">` +
    '<span class="vals"><span class="v editable" title="點兩下輸入數值"></span><span class="cn"></span></span>' +
    '<button class="reset" title="還原這一項的微調（回到 preset × 強度）">↺</button>';
  row.querySelector('label').textContent = s.label;
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
    acc.querySelector('.tc').textContent = n ? `● 微調 ${n} 項` : '';
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
  $('#strength-value').textContent = on ? ed.strength + '%' : '—';
  $('#strength').title = on ? '' : '先選一個 preset';
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
  for (const [label, fn] of items) {
    const b = document.createElement('button');
    b.setAttribute('role', 'menuitem'); b.textContent = label;
    b.onclick = (e) => { e.stopPropagation(); closeMenu(); fn(); };
    m.appendChild(b);
  }
  const r = anchor.getBoundingClientRect();
  m.style.left = Math.min(r.left, window.innerWidth - 180) + 'px'; m.style.top = (r.bottom + 2) + 'px';
  document.body.appendChild(m);
  m.querySelector('button').focus();
  m.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeMenu(); anchor.focus(); } });
}

function askNewGroup(base) {
  const g = prompt('新群組名稱（用「 - 」分層）', base ? base + ' - ' : '');
  if (g !== null) libraryCall('groups/create', {group: g}, (r) => L.groupCreated(r.group));
}

function presetMenu(p, anchor) {
  showMenu(anchor, [
    ['改名…', () => { const n = prompt('preset 名稱', p.name); if (n !== null) libraryCall('rename', {preset_id: p.id, name: n}); }],
    ['搬到…', () => { const g = prompt('搬到群組（用「 - 」分層）', p.group); if (g !== null) libraryCall('move', {preset_id: p.id, group: g}); }],
    ['新群組…', () => askNewGroup(p.group)],
  ]);
}

function groupMenu(path, anchor) {
  showMenu(anchor, [
    ['群組改名…', () => { const n = prompt('群組的新名稱（完整路徑）', path); if (n !== null) libraryCall('groups/rename', {group: path, new_name: n}); }],
    ['新群組…', () => askNewGroup(path)],
  ]);
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
function refreshSavePreset() { $('#save-preset-btn').disabled = !L.canSavePreset(ed); }

async function savePreset() {
  if (!L.canSavePreset(ed)) return;
  const name = prompt('自存 preset 的名稱', ed.presetId !== null && st.byId[ed.presetId] ? st.byId[ed.presetId].name : '');
  if (name === null) return;
  const group = prompt('群組（用「 - 」分層）', L.USER_GROUP);
  if (group === null) return;
  if (st.image) await flushSave();
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
  await flushSave();                    // the previous photo's last change goes out first (PL15)
  const token = ++openSeq;
  setStatus('讀取照片中…', 'busy');
  let info;
  try { info = await (await api('POST', '/api/open', {path})).json(); }
  catch (e) { if (token === openSeq) openFailed(path, e.message); return; }
  if (token !== openSeq) return;
  // from here until the saved edit is restored nothing is scheduled for saving (S1): the state is in transit
  st.loading = token;
  st.image = Object.assign(info, {path});
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
const save = {timer: null, dirty: false, pending: null, promise: null};

function scheduleSave() {
  if (!st.image || st.loading) return;
  const path = st.image.path;
  save.pending = {path, req: L.editRequest(ed, path, st.snapshots, st.fingerprint), retried: false};
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
      setTimeout(() => {
        if (!save.pending && st.image && st.image.path === path) {
          save.pending = Object.assign({}, job, {retried: true}); save.dirty = true; flushSave();
        }
      }, L.SAVE_RETRY_MS);
    }
  }
}

async function flushSave() {            // sends what is pending and waits until nothing is in flight
  clearTimeout(save.timer); save.timer = null;
  while (save.pending || save.promise) {
    if (save.promise) { await save.promise; continue; }
    const job = save.pending; save.pending = null; save.dirty = false;
    save.promise = sendSave(job).finally(() => { save.promise = null; });
  }
}

function unloadSave() {                 // S13 (g): the newest body goes out at once, not after the one in flight
  const job = save.pending;
  if (!job) return;
  save.pending = null; save.dirty = false;
  sendSave(job);
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

function showGrid(on) {
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
  st.grid = {folder: res.folder, items: res.items, sel: new Set(), anchor: 0};
  $('#grid-path').value = res.folder;
  renderGrid();
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
  st.grid.items.forEach((it, i) => {
    const cell = document.createElement('div');
    cell.className = 'cell' + (it.edited ? ' edited' : '');
    cell.dataset.path = it.path; cell.dataset.i = String(i); cell.tabIndex = i ? -1 : 0;
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
        const n = box.children[i + (e.key === 'ArrowRight' ? 1 : -1)];
        if (n) { e.preventDefault(); n.focus(); }
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
    cell.classList.toggle('edited', r.headers.get('X-Edited') === '1');
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
  st.grid.sel = r.sel; st.grid.anchor = r.anchor;
  renderGridSelection();
}

function renderGridSelection() {
  const cells = $('#grid-cells').children;
  for (const c of cells) c.classList.toggle('selected', st.grid.sel.has(+c.dataset.i));
  $('#grid-count').textContent = L.gridCount(st.grid.sel.size, st.grid.items.length);
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
  if (!confirm(L.pasteConfirm(st.clipboard.name, targets.length))) return;
  let res;
  try { res = await (await api('POST', '/api/edit/paste', {targets, edit: st.clipboard.edit})).json(); }
  catch (e) { toast(e.message, true); return; }
  gridBatchDone(L.pasteDone, targets, res.results);
  markCells(targets, res.results, 'edited');
  if (st.image && targets.includes(st.image.path)) await loadEdit(st.image.path);
}

async function exportSelected() {       // each photo with its own saved edit; format / quality from the toolbar
  const paths = selectedPaths();
  if (!paths.length || exp.busy) return;
  exp.busy = true;                      // S13 (a): a second click must not export everything twice
  const btn = $('#export-selected-btn');
  btn.disabled = true; btn.textContent = L.EXPORT_BUSY;
  try {
    await flushSave();
    const edits = {}, lines = [];
    for (const p of paths) {
      try { edits[p] = await (await api('GET', '/api/edit?path=' + encodeURIComponent(p))).json(); }
      catch (e) { edits[p] = null; lines.push(`${L.baseName(p)}：${L.loadEditFailed(L.explain(e.message))}`); }
    }
    const {items, failed} = L.exportItems(paths, edits);
    let ok = 0, fail = failed;
    if (items.length) {
      const format = $('#export-format').value;
      const body = {items, format};
      if (format === 'jpeg') body.quality = L.exportBody({}, format, $('#export-quality').value).quality;
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
  $('#export-quality').disabled = $('#export-format').value !== 'jpeg';
}

async function commitCarried() {        // S11: a carried-over state becomes this photo's edit before it is exported
  if (!st.image || st.edit || !L.carryHintVisible(ed, true, false)) return;
  scheduleSave();
  await flushSave();
}

async function exportPhoto() {
  if (!st.image || exp.busy) return;
  exp.busy = true;
  refreshExport();
  const name = L.baseName(st.image.path);
  await commitCarried();
  try {
    const res = await (await api('POST', '/api/export',
      L.exportBody(currentRequest(), $('#export-format').value, $('#export-quality').value))).json();
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

// ------------------------------------------------------------------ wiring
const typing = (el) => el && (el.matches('input[type=text], input[type=search], input[type=number]') || el.isContentEditable);
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
  });
  $('#reset-all').onclick = () => dispatch({type: 'resetAll'});
  $('#export-btn').onclick = exportPhoto;
  $('#save-preset-btn').onclick = savePreset;
  $('#import-btn').onclick = () => $('#import-file').click();
  $('#import-file').addEventListener('change', (e) => { const fl = [...e.target.files]; e.target.value = ''; importFiles(fl); });
  $('#new-group-btn').onclick = () => askNewGroup('');
  document.addEventListener('click', (e) => { if (!e.target.closest('.menu-pop')) closeMenu(); });
  $('#export-format').addEventListener('change', refreshExport);
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
  $('#export-selected-btn').onclick = exportSelected;
  window.addEventListener('beforeunload', () => { if (save.dirty) unloadSave(); });
  refreshCopy();
  $('#search').addEventListener('input', (e) => { st.search = e.target.value.trim(); renderTree(); });
  $('#preset-tree').addEventListener('keydown', onTreeKey);
  const hold = $('#hold');
  hold.addEventListener('pointerdown', () => showOriginal(true));
  for (const ev of ['pointerup', 'pointerleave']) hold.addEventListener(ev, () => { if (st.holding) showOriginal(false); });
  document.addEventListener('keydown', (e) => {
    if (typing(e.target)) return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); redo(); return; }
    if (e.target.closest && (e.target.closest('#preset-tree') || e.target.closest('#grid'))) return;
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
  // S15: ?path= only fills the box (a link from outside the browser must not make the app read a path);
  // the last opened photo is restored as before
  const q = new URLSearchParams(location.search).get('path');
  const last = loadPref('lastPath', '');
  if (q) $('#photo-path').value = q;
  else if (last) { $('#photo-path').value = last; openPhoto(last); }
}

window.darkroom = {st, pv, get ed() { return ed; }, dispatch, requestPreview, selectPreset, openPhoto, step, undo, redo, setStrength,
                   exportPhoto, savePreset, importFiles, reloadLibrary,
                   flushSave, loadEdit, showGrid, loadGrid, copyEdit, pasteEdit, exportSelected};
init().catch((e) => toast('載入失敗：' + e.message, true));
