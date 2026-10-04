'use strict';
// darkroom editor: preset tree (left), backend-rendered preview (centre), sliders (right).
// Every preview comes from the backend (POST /api/preview); the page never fakes colour changes.
// Pure logic (slider semantics, history, tree keys, search, typed values, curves) lives in logic.js.

const L = window.DarkroomLogic;
const $ = (s) => document.querySelector(s);
const NO_PRESET = '（未選）';
const STRENGTH = {min: 0, max: 200, step: 1};
const NARROW = window.matchMedia('(max-width: 960px)');

const st = {
  presets: [], byId: {}, flags: {}, sliders: [], groups: [], byKey: {},
  image: null, folder: null,
  presetId: null, detail: null,
  strength: 100, tweaks: {},
  search: '', openFolders: {}, openGroups: loadPref('openGroups', {basic: true}), hslTab: 'h', focusKey: null,
  holding: false, originalUrl: null, originalFor: null,
};
const history = new L.History(200);

function loadPref(k, dflt) {
  try { const v = localStorage.getItem('darkroom.' + k); return v ? JSON.parse(v) : dflt; } catch (e) { return dflt; }
}
function savePref(k, v) { try { localStorage.setItem('darkroom.' + k, JSON.stringify(v)); } catch (e) { /* optional */ } }

let toastT = null;
function toast(msg, err) {
  const t = $('#toast'); t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toastT); toastT = setTimeout(() => { t.className = ''; }, 2600);
}
function setStatus(msg, cls, detail) {
  const s = $('#status'); s.textContent = msg; s.className = cls || 'mute'; s.title = detail || msg;
}

async function api(method, url, body) {
  const r = await fetch(url, {method, headers: body ? {'Content-Type': 'application/json'} : {},
                              body: body ? JSON.stringify(body) : undefined});
  if (!r.ok) {
    let msg = r.status + '';
    try { msg = (await r.json()).error || msg; } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  return r;
}

// ------------------------------------------------------------------ state, history (R5)
function snapshot() { return {presetId: st.presetId, strength: st.strength, tweaks: Object.assign({}, st.tweaks)}; }
function record() { history.push(snapshot()); refreshUndo(); }
function refreshUndo() { $('#undo').disabled = !history.canUndo(); $('#redo').disabled = !history.canRedo(); }

async function applyState(s) {
  if (!s) return;
  const presetChanged = s.presetId !== st.presetId;
  st.strength = s.strength;
  st.tweaks = Object.assign({}, s.tweaks);
  if (presetChanged) await loadPreset(s.presetId);
  else renderStrength();
  renderSliders();
  refreshUndo();
  requestPreview();
}
function undo() { applyState(history.undo(snapshot())); }
function redo() { applyState(history.redo(snapshot())); }

// ------------------------------------------------------------------ slider values (R3)
function presetValue(key) {
  const s = st.byKey[key];
  return st.detail && st.detail.values[key] != null ? st.detail.values[key] : s.default;
}
const strengthNow = () => (st.presetId === null ? 100 : st.strength);
function view(key) { return L.sliderView(st.byKey[key], presetValue(key), strengthNow(), st.tweaks[key] || 0); }
function setTweak(key, value) {
  const d = L.tweakFor(st.byKey[key], presetValue(key), strengthNow(), value);
  if (d) st.tweaks[key] = d; else delete st.tweaks[key];
}

// ------------------------------------------------------------------ preview: latest wins
// Only the newest parameters wait to be sent; older ones are overwritten, never queued.
const pv = {pending: null, inflight: false, seq: 0, shownSeq: 0, url: null};

function currentRequest() {
  const overrides = {};
  for (const [k, d] of Object.entries(st.tweaks)) if (d) overrides[k] = d;
  return {image_id: st.image.image_id, preset_id: st.presetId, strength: strengthNow(), overrides};
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
  el.className = 'tnode preset' + (p.id === st.presetId ? ' active' : '') + (p.supported ? '' : ' unsupported');
  el.style.paddingLeft = (6 + depth * 14) + 'px';
  el.dataset.id = p.id;
  el.innerHTML = `<span class="tw"></span><span class="nm"></span>${flagHtml(p)}` + (showPath ? '<span class="path"></span>' : '');
  el.querySelector('.nm').textContent = p.name;
  if (showPath) el.querySelector('.path').textContent = p.group;
  el.title = p.group ? p.group + ' / ' + p.name : p.name;
  if (p.supported) el.onclick = () => { st.focusKey = 'p:' + p.id; selectPreset(p.id); };
  return el;
}

function folderEl(name, key, count, depth) {
  const open = !!st.openFolders[key];
  const el = document.createElement('div');
  el.className = 'tnode folder';
  el.style.paddingLeft = (6 + depth * 14) + 'px';
  el.innerHTML = `<span class="tw">${open ? '▼' : '▶'}</span><span class="nm"></span><span class="cnt">${count}</span>`;
  el.querySelector('.nm').textContent = name;
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
  none.className = 'tnode preset none' + (st.presetId === null ? ' active' : '');
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
    for (const [top, node] of buildTree()) {
      const count = node.items.length + [...node.subs.values()].reduce((a, l) => a + l.length, 0);
      const topIdx = treeRows.length;
      addRow(folderEl(top, top, count, 0), {type: 'folder', key: 'f:' + top, fkey: top, depth: 0, open: !!st.openFolders[top], parent: -1});
      if (!st.openFolders[top]) continue;
      for (const [sub, list] of node.subs) {
        const key = top + '\u0000' + sub;
        const subIdx = treeRows.length;
        addRow(folderEl(sub, key, list.length, 1), {type: 'folder', key: 'f:' + key, fkey: key, depth: 1, open: !!st.openFolders[key], parent: topIdx});
        if (st.openFolders[key]) list.forEach((p) => addRow(presetEl(p, 2, false), {type: 'preset', key: 'p:' + p.id, id: p.id, depth: 2, parent: subIdx}));
      }
      node.items.forEach((p) => addRow(presetEl(p, 1, false), {type: 'preset', key: 'p:' + p.id, id: p.id, depth: 1, parent: topIdx}));
    }
  }
  // roving tabindex: exactly one row can be reached with Tab
  let fi = treeRows.findIndex((r) => r.key === st.focusKey);
  if (fi < 0) fi = treeRows.findIndex((r) => r.type === 'preset' && r.id === st.presetId);
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
  st.presetId = id;
  st.detail = null;
  if (id !== null) {
    try { st.detail = await (await api('GET', '/api/presets/' + encodeURIComponent(id))).json(); }
    catch (e) { toast('讀取 preset 失敗：' + e.message, true); }
    if (st.presetId !== id) return;
  }
  $('#preset-name').textContent = id === null ? NO_PRESET : st.byId[id].name;
  const banner = $('#skip-banner'), note = $('#skip-note');
  const b = st.detail ? st.detail.banner : '', n = st.detail ? st.detail.note : '';
  banner.textContent = b; banner.title = b; banner.hidden = !b;
  note.textContent = n; note.title = n; note.hidden = !n;
  renderStrength();
  renderTree();
}

async function selectPreset(id) {
  if (id === st.presetId) return;
  record();                       // strength and tweaks are kept (R5)
  await loadPreset(id);
  renderSliders();
  requestPreview();
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
  row.classList.toggle('adjusted', !!st.tweaks[key]);
  row.classList.toggle('clamped', !!v.clamped);
  const inp = row.querySelector('input[type=range]');
  if (document.activeElement !== inp || !row.dragging) inp.value = v.value;
  const vs = row.querySelector('.v');
  if (!vs.querySelector('input')) vs.textContent = L.fmtNum(s, v.value);
  row.querySelector('.cn').textContent = L.clampNote(v);
  row.title = L.sliderTooltip(s, presetValue(key), strengthNow(), st.tweaks[key] || 0);
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
  let gesture = false;
  inp.addEventListener('input', () => {
    if (!gesture) { record(); gesture = true; }      // one history step per drag
    row.dragging = true;
    setTweak(s.key, +inp.value);
    updateRow(row);
    refreshBadges();
    requestPreview();
  });
  inp.addEventListener('change', () => { gesture = false; row.dragging = false; updateRow(row); });
  const reset = () => { if (st.tweaks[s.key]) { record(); delete st.tweaks[s.key]; updateRow(row); refreshBadges(); requestPreview(); } };
  inp.addEventListener('dblclick', reset);
  row.querySelector('label').addEventListener('dblclick', reset);
  row.querySelector('.reset').addEventListener('click', reset);
  const vs = row.querySelector('.v');
  vs.addEventListener('dblclick', () => editValue(vs, L.fmtNum(s, view(s.key).value).replace(/^\+/, ''), s, (v) => {
    record(); setTweak(s.key, v); updateRow(row); refreshBadges(); requestPreview();
  }));
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
    const n = st.sliders.filter((s) => s.group === g && st.tweaks[s.key]).length;
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
  const none = st.presetId === null;
  $('#strength').disabled = none;
  $('#strength-100').disabled = none;
  $('#strength').value = st.strength;
  $('#strength-value').textContent = none ? '—' : st.strength + '%';
  $('#strength').title = none ? '先選一個 preset' : '';
}

let strengthGesture = false;
function onStrength() {
  if (!strengthGesture) { record(); strengthGesture = true; }
  st.strength = +$('#strength').value;
  $('#strength-value').textContent = st.strength + '%';
  refreshSliderValues();
  requestPreview();
}
function setStrength(v) {
  if (st.presetId === null || v === st.strength) return;
  record();
  st.strength = v;
  renderStrength();
  refreshSliderValues();
  requestPreview();
}

// ------------------------------------------------------------------ photos
async function openPhoto(path) {
  path = (path || '').trim().replace(/^"|"$/g, '');
  if (!path) return;
  setStatus('讀取照片中…', 'busy');
  let info;
  try { info = await (await api('POST', '/api/open', {path})).json(); }
  catch (e) { setStatus('預覽：待命'); toast('開啟失敗：' + e.message, true); return; }
  st.image = Object.assign(info, {path});
  $('#photo-path').value = path;
  savePref('lastPath', path);
  $('#photo-size').textContent = `${info.width}×${info.height}`;
  $('#photo-size').title = `預覽 ${info.preview_width}×${info.preview_height}`;
  try { st.folder = await (await api('GET', '/api/folder?image_id=' + info.image_id)).json(); }
  catch (e) { st.folder = null; }
  renderPosition();
  requestPreview();
}

function renderPosition() {
  const f = st.folder;
  $('#carry-hint').hidden = !st.image;
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
const typing = (el) => el && (el.matches('input[type=text], input[type=search]') || el.isContentEditable);

async function init() {
  $('#open-form').addEventListener('submit', (e) => { e.preventDefault(); openPhoto($('#photo-path').value); });
  $('#prev').onclick = () => step(-1);
  $('#next').onclick = () => step(1);
  $('#undo').onclick = undo;
  $('#redo').onclick = redo;
  $('#toggle-lib').onclick = toggleLib;
  $('#toggle-sl').onclick = () => document.body.classList.toggle('sl-collapsed');
  $('#strength').addEventListener('input', onStrength);
  $('#strength').addEventListener('change', () => { strengthGesture = false; });
  $('#strength-100').onclick = () => setStrength(100);
  $('#strength-value').addEventListener('dblclick', () => {
    if (st.presetId === null) return;
    editValue($('#strength-value'), String(st.strength), STRENGTH, (v) => setStrength(Math.round(v)));
  });
  $('#reset-all').onclick = () => { if (Object.keys(st.tweaks).length) { record(); st.tweaks = {}; renderSliders(); requestPreview(); } };
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
    if (e.target.closest && e.target.closest('#preset-tree')) return;
    if (e.key === '\\' && !e.repeat) showOriginal(true);
    else if (e.key === 'ArrowLeft' && !e.target.matches('input')) step(-1);
    else if (e.key === 'ArrowRight' && !e.target.matches('input')) step(1);
  });
  document.addEventListener('keyup', (e) => { if (e.key === '\\' && st.holding) showOriginal(false); });

  const [presets, sl, flags] = await Promise.all([
    api('GET', '/api/presets').then((r) => r.json()),
    api('GET', '/api/sliders').then((r) => r.json()),
    api('GET', '/api/preset_flags').then((r) => r.json()),
  ]);
  st.presets = presets; st.flags = flags;
  presets.forEach((p) => { st.byId[p.id] = p; });
  st.sliders = sl.sliders; st.groups = sl.groups;
  sl.sliders.forEach((s) => { st.byKey[s.key] = s; });
  renderTree();
  renderStrength();
  renderSliders();
  refreshUndo();
  const q = new URLSearchParams(location.search).get('path');
  const last = q || loadPref('lastPath', '');
  if (last) { $('#photo-path').value = last; openPhoto(last); }
}

window.darkroom = {st, pv, history, requestPreview, selectPreset, openPhoto, step, undo, redo, setStrength};
init().catch((e) => toast('載入失敗：' + e.message, true));
