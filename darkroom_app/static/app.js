'use strict';
// darkroom editor: preset tree (left), backend-rendered preview (centre), sliders (right).
// Every preview comes from the backend (POST /api/preview); the page never fakes colour changes.

const $ = (s) => document.querySelector(s);
const NO_PRESET = '（未選）';

const st = {
  presets: [], byId: {}, sliders: [], groups: [], byKey: {},
  image: null,            // {image_id, width, height, preview_width, preview_height, path}
  folder: null,           // {files: [{name, path}], index}
  presetId: null, detail: null,
  strength: 100, tweaks: {},
  search: '', openFolders: {}, openGroups: loadPref('openGroups', {basic: true}), hslTab: 'h',
  holding: false, originalUrl: null, originalFor: null,
};

function loadPref(k, dflt) {
  try { const v = localStorage.getItem('darkroom.' + k); return v ? JSON.parse(v) : dflt; } catch (e) { return dflt; }
}
function savePref(k, v) { try { localStorage.setItem('darkroom.' + k, JSON.stringify(v)); } catch (e) { /* optional */ } }

let toastT = null;
function toast(msg, err) {
  const t = $('#toast'); t.textContent = msg; t.className = 'show' + (err ? ' err' : '');
  clearTimeout(toastT); toastT = setTimeout(() => { t.className = ''; }, 2600);
}
function setStatus(msg, cls) { const s = $('#status'); s.textContent = msg; s.className = cls || 'mute'; }

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

// ------------------------------------------------------------------ slider values
// base = preset value at the current strength (hue angles are not scaled); shown = clamp(base + tweak).
function presetValue(key) {
  const s = st.byKey[key];
  return st.detail && st.detail.values[key] != null ? st.detail.values[key] : s.default;
}
function baseVal(key) {
  const s = st.byKey[key], v = presetValue(key);
  if (s.hue) return v;
  return s.default + (st.strength / 100) * (v - s.default);
}
function clampKey(key, v) { const s = st.byKey[key]; return Math.min(s.max, Math.max(s.min, v)); }
function shownVal(key) { return clampKey(key, baseVal(key) + (st.tweaks[key] || 0)); }
function fmt(key, v) {
  const s = st.byKey[key];
  if (s.step < 1) return (v > 0 && s.min < 0 ? '+' : '') + v.toFixed(2);
  v = Math.round(v);
  return (v > 0 && s.min < 0 ? '+' : '') + v;
}

// ------------------------------------------------------------------ preview: latest wins
// Only the newest parameters wait to be sent; older ones are overwritten, never queued.
const pv = {pending: null, inflight: false, seq: 0, shownSeq: 0, url: null};

function currentRequest() {
  const overrides = {};
  for (const [k, d] of Object.entries(st.tweaks)) if (d) overrides[k] = d;
  return {image_id: st.image.image_id, preset_id: st.presetId, strength: st.strength, overrides};
}

function requestPreview() {
  if (!st.image) return;
  pv.pending = {body: currentRequest(), seq: ++pv.seq, t: performance.now()};
  if (!pv.inflight) pump();
}

async function pump() {
  pv.inflight = true;
  setStatus('後端算圖中…', 'busy');
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
      const img = $('#preview-img');
      if (!st.holding) {
        await swapImage(img, url);
      }
      if (pv.url) URL.revokeObjectURL(pv.url);
      pv.url = url;
      if (!pv.pending) {
        setStatus(`預覽：已更新（後端 ${(+ms).toFixed(0)} ms，往返 ${(performance.now() - t0).toFixed(0)} ms）`);
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

// ------------------------------------------------------------------ preset tree
function splitGroup(group) {
  // two levels: text before the first " - ", then the rest
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

function presetRow(p, depth, showPath) {
  const el = document.createElement('div');
  el.className = 'tnode preset' + (p.id === st.presetId ? ' active' : '') + (p.supported ? '' : ' unsupported');
  el.style.paddingLeft = (6 + depth * 14) + 'px';
  el.dataset.id = p.id;
  el.setAttribute('role', 'treeitem');
  const flag = !p.supported ? '<span class="flag" title="不支援的 preset">⛔</span>'
    : (p.skipped.length ? `<span class="flag" title="有 ${p.skipped.length} 項設定無法套用">⚠</span>` : '');
  el.innerHTML = `<span class="tw"></span><span class="nm"></span>${flag}` + (showPath ? '<span class="path"></span>' : '');
  el.querySelector('.nm').textContent = p.name;
  if (showPath) el.querySelector('.path').textContent = p.group;
  el.title = p.group ? p.group + ' / ' + p.name : p.name;
  if (p.supported) el.onclick = () => selectPreset(p.id);
  return el;
}

function folderRow(name, key, count, depth) {
  const open = !!st.openFolders[key];
  const el = document.createElement('div');
  el.className = 'tnode folder';
  el.style.paddingLeft = (6 + depth * 14) + 'px';
  el.innerHTML = `<span class="tw">${open ? '▼' : '▶'}</span><span class="nm"></span><span class="cnt">${count}</span>`;
  el.querySelector('.nm').textContent = name;
  el.onclick = () => { st.openFolders[key] = !open; renderTree(); };
  return el;
}

function renderTree() {
  const box = $('#preset-tree');
  const scroll = box.scrollTop;
  box.innerHTML = '';
  $('#lib-count').textContent = `preset 庫（${st.presets.length} 個）`;
  const none = document.createElement('div');
  none.className = 'tnode preset none' + (st.presetId === null ? ' active' : '');
  none.innerHTML = '<span class="tw"></span><span class="nm">（不套 preset，只用微調）</span>';
  none.onclick = () => selectPreset(null);
  box.appendChild(none);
  if (st.search) {
    const q = st.search.toLowerCase();
    const hits = st.presets.filter((p) => p.name.toLowerCase().includes(q));
    const n = document.createElement('div');
    n.className = 'sec-title'; n.textContent = `找到 ${hits.length} 個`;
    box.appendChild(n);
    hits.forEach((p) => box.appendChild(presetRow(p, 0, true)));
    return;
  }
  for (const [top, node] of buildTree()) {
    const count = node.items.length + [...node.subs.values()].reduce((a, l) => a + l.length, 0);
    box.appendChild(folderRow(top, top, count, 0));
    if (!st.openFolders[top]) continue;
    for (const [sub, list] of node.subs) {
      const key = top + '\u0000' + sub;
      box.appendChild(folderRow(sub, key, list.length, 1));
      if (st.openFolders[key]) list.forEach((p) => box.appendChild(presetRow(p, 2, false)));
    }
    node.items.forEach((p) => box.appendChild(presetRow(p, 1, false)));
  }
  box.scrollTop = scroll;
}

async function selectPreset(id) {
  st.presetId = id;
  st.strength = 100;      // picking a preset resets strength and clears every tweak
  st.tweaks = {};
  st.detail = null;
  $('#strength').value = 100; $('#strength-value').textContent = '100%';
  if (id !== null) {
    try { st.detail = await (await api('GET', '/api/presets/' + encodeURIComponent(id))).json(); }
    catch (e) { toast('讀取 preset 失敗：' + e.message, true); return; }
    if (st.presetId !== id) return;
  }
  $('#preset-name').textContent = id === null ? NO_PRESET : st.byId[id].name;
  const banner = $('#skip-banner');
  const text = st.detail ? st.detail.banner : '';
  banner.textContent = text;
  banner.hidden = !text;
  renderTree();
  renderSliders();
  requestPreview();
}

// ------------------------------------------------------------------ sliders
function sliderRow(s) {
  const row = document.createElement('div');
  const tw = st.tweaks[s.key];
  row.className = 'sl' + (tw ? ' adjusted' : '');
  row.dataset.key = s.key;
  const v = shownVal(s.key);
  row.innerHTML = `<label></label><input type="range" min="${s.min}" max="${s.max}" step="${s.step}">` +
    '<span class="v"></span><button class="reset" title="還原這一項的微調（回到 preset × 強度）">↺</button>';
  row.querySelector('label').textContent = s.label;
  const inp = row.querySelector('input');
  inp.value = v;
  inp.setAttribute('aria-label', s.label);
  row.querySelector('.v').textContent = fmt(s.key, v);
  const tip = () => {
    const t = st.tweaks[s.key];
    row.title = `preset × 強度 ${st.strength}% = ${fmt(s.key, baseVal(s.key))}` +
      (t ? `；微調 ${t > 0 ? '+' : ''}${+t.toFixed(2)}` : '') + '；雙擊＝還原這一項';
  };
  tip();
  inp.addEventListener('input', () => {
    const nv = +inp.value;
    let d = nv - baseVal(s.key);
    if (Math.abs(d) < s.step / 2) d = 0;
    if (d) st.tweaks[s.key] = d; else delete st.tweaks[s.key];
    row.classList.toggle('adjusted', !!d);
    row.querySelector('.v').textContent = fmt(s.key, nv);
    tip();
    refreshBadges();
    requestPreview();
  });
  const reset = () => { resetTweak(s.key); };
  inp.addEventListener('dblclick', reset);
  row.querySelector('.reset').addEventListener('click', reset);
  return row;
}

function resetTweak(key) {
  delete st.tweaks[key];
  renderSliders();
  requestPreview();
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
    acc.innerHTML = `<div class="ah"><span class="tw">${open ? '▼' : '▶'}</span><span></span><span class="tc"></span></div><div class="ab"></div>`;
    acc.querySelector('.ah span:nth-child(2)').textContent = gname;
    acc.querySelector('.ah').onclick = () => { st.openGroups[g] = !open; savePref('openGroups', st.openGroups); renderSliders(); };
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
  document.querySelectorAll('#sliders .sl').forEach((row) => {
    const key = row.dataset.key, v = shownVal(key);
    row.querySelector('input').value = v;
    row.querySelector('.v').textContent = fmt(key, v);
  });
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
  $('#photo-size').textContent = `${info.width}×${info.height}（預覽 ${info.preview_width}×${info.preview_height}）`;
  try { st.folder = await (await api('GET', '/api/folder?image_id=' + info.image_id)).json(); }
  catch (e) { st.folder = null; }
  renderPosition();
  requestPreview();
}

function renderPosition() {
  const f = st.folder;
  if (!f || f.index < 0) { $('#position').textContent = st.image ? st.image.path : '尚未開啟照片'; $('#prev').disabled = $('#next').disabled = true; return; }
  $('#position').textContent = `${f.index + 1} / ${f.files.length}　${f.files[f.index].name}`;
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

// ------------------------------------------------------------------ wiring
function onStrength() {
  st.strength = +$('#strength').value;
  $('#strength-value').textContent = st.strength + '%';
  refreshSliderValues();
  requestPreview();
}

async function init() {
  $('#open-form').addEventListener('submit', (e) => { e.preventDefault(); openPhoto($('#photo-path').value); });
  $('#prev').onclick = () => step(-1);
  $('#next').onclick = () => step(1);
  $('#strength').addEventListener('input', onStrength);
  $('#strength-100').onclick = () => { $('#strength').value = 100; onStrength(); };
  $('#reset-all').onclick = () => { st.tweaks = {}; renderSliders(); requestPreview(); };
  $('#search').addEventListener('input', (e) => { st.search = e.target.value.trim(); renderTree(); });
  const hold = $('#hold');
  hold.addEventListener('pointerdown', () => showOriginal(true));
  for (const ev of ['pointerup', 'pointerleave']) hold.addEventListener(ev, () => { if (st.holding) showOriginal(false); });
  document.addEventListener('keydown', (e) => {
    if (e.target.matches('input[type=text], input[type=search]')) return;
    if (e.key === '\\' && !e.repeat) showOriginal(true);
    else if (e.key === 'ArrowLeft' && !e.target.matches('input')) step(-1);
    else if (e.key === 'ArrowRight' && !e.target.matches('input')) step(1);
  });
  document.addEventListener('keyup', (e) => { if (e.key === '\\' && st.holding) showOriginal(false); });

  const [presets, sl] = await Promise.all([
    api('GET', '/api/presets').then((r) => r.json()),
    api('GET', '/api/sliders').then((r) => r.json()),
  ]);
  st.presets = presets;
  presets.forEach((p) => { st.byId[p.id] = p; });
  st.sliders = sl.sliders; st.groups = sl.groups;
  sl.sliders.forEach((s) => { st.byKey[s.key] = s; });
  renderTree();
  renderSliders();
  const q = new URLSearchParams(location.search).get('path');
  const last = q || loadPref('lastPath', '');
  if (last) { $('#photo-path').value = last; openPhoto(last); }
}

window.darkroom = {st, pv, requestPreview, selectPreset, openPhoto, step};
init().catch((e) => toast('載入失敗：' + e.message, true));
