// Front-end logic (darkroom_app/static/logic.js): contract R3 (slider semantics), R5 (history),
// R6 (tree keyboard, search, value input, curve at strength). Run: node --test tests/js/test_logic.cjs
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const L = require(path.join(__dirname, '..', '..', 'darkroom_app', 'static', 'logic.js'));

const CONTRAST = {key: 'Contrast2012', min: -100, max: 100, default: 0, step: 1, hue: false};
const EXPO = {key: 'Exposure2012', min: -5, max: 5, default: 0, step: 0.05, hue: false};
const HUE = {key: 'SplitToningShadowHue', min: 0, max: 360, default: 0, step: 1, hue: true};
const GRAIN = {key: 'GrainSize', min: 0, max: 100, default: 25, step: 1, hue: false};

test('R3: view clamps preset x strength before adding the tweak', () => {
  const v = L.sliderView(CONTRAST, -75, 150, 0);
  assert.equal(v.raw, -112.5);
  assert.equal(v.base, -100);
  assert.equal(v.value, -100);
  assert.equal(v.clamped, 'min');
  const w = L.sliderView(CONTRAST, -75, 150, 10);
  assert.equal(w.value, -90);                       // clamp(clamp(-112.5) + 10)
  assert.equal(L.sliderView(CONTRAST, 80, 150, 0).clamped, 'max');
  assert.equal(L.sliderView(CONTRAST, 40, 100, 0).clamped, null);
  assert.equal(L.sliderView(HUE, 200, 50, 30).value, 230);   // hue angles are not scaled
  assert.equal(L.sliderView(GRAIN, 25, 200, 5).value, 30);   // default 25 stays 25 at any strength
});

test('R3: tweak is measured from the value shown on screen', () => {
  assert.equal(L.tweakFor(CONTRAST, -75, 150, -100), 0);     // not +12.5
  assert.equal(L.tweakFor(CONTRAST, -75, 150, -90), 10);
  assert.equal(L.tweakFor(CONTRAST, -75, 150, -100.3), 0);   // below half a step
  assert.ok(Math.abs(L.tweakFor(EXPO, 1.0, 50, 0.8) - 0.3) < 1e-9);
  assert.equal(L.tweakFor(EXPO, 1.0, 50, 0.51), 0);
  assert.equal(L.tweakFor(CONTRAST, 0, 100, 150), 100);      // input beyond the range is clamped first
});

test('R3: tooltip follows strength and reports clamping', () => {
  assert.equal(L.sliderTooltip(CONTRAST, -75, 150, 0), 'preset × 150% = -112.5，已到下限 -100；雙擊＝還原這一項');
  assert.equal(L.sliderTooltip(CONTRAST, -75, 100, 0), 'preset × 100% = -75；雙擊＝還原這一項');
  assert.equal(L.sliderTooltip(CONTRAST, 80, 150, -5), 'preset × 150% = 120，已到上限 100；微調 -5；雙擊＝還原這一項');
  assert.equal(L.clampNote(L.sliderView(CONTRAST, -75, 150, 0)), '（原 -112.5）');
  assert.equal(L.clampNote(L.sliderView(CONTRAST, -50, 150, 0)), '');
});

test('R5: history keeps at least 50 steps of preset, strength and tweaks', () => {
  const h = new L.History();
  let cur = {presetId: null, strength: 100, tweaks: {}};
  const states = [cur];
  for (let i = 1; i <= 60; i++) {
    h.push(cur);
    cur = {presetId: 'p' + (i % 3), strength: 100 + i, tweaks: {Contrast2012: i}};
    states.push(cur);
  }
  for (let i = 59; i >= 10; i--) {      // 50 undos
    cur = h.undo(cur);
    assert.deepEqual(cur, states[i]);
  }
  assert.ok(h.canRedo());
  cur = h.redo(cur);
  assert.deepEqual(cur, states[11]);
  h.push(cur);                          // a new change drops the redo branch
  assert.equal(h.canRedo(), false);
});

test('R5: history snapshots are copies and identical pushes collapse', () => {
  const h = new L.History();
  const s = {presetId: 'a', strength: 100, tweaks: {X: 1}};
  h.push(s);
  s.tweaks.X = 99;                      // mutating the live state must not change the record
  h.push({presetId: 'a', strength: 100, tweaks: {X: 99}});
  h.push({presetId: 'a', strength: 100, tweaks: {X: 99}});   // duplicate of the last record
  const cur = {presetId: 'b', strength: 50, tweaks: {}};
  const u1 = h.undo(cur);
  assert.deepEqual(u1, {presetId: 'a', strength: 100, tweaks: {X: 99}});
  const u2 = h.undo(u1);
  assert.deepEqual(u2, {presetId: 'a', strength: 100, tweaks: {X: 1}});
  assert.equal(h.undo(u2), null);
  assert.equal(new L.History().undo(cur), null);
});

test('R6: tree keyboard', () => {
  const rows = [
    {type: 'folder', key: 'A', depth: 0, open: true, parent: -1},
    {type: 'folder', key: 'A/x', depth: 1, open: false, parent: 0},
    {type: 'preset', key: 'p1', depth: 1, parent: 0},
    {type: 'folder', key: 'B', depth: 0, open: false, parent: -1},
  ];
  assert.deepEqual(L.treeKey(rows, 0, 'ArrowDown'), {focus: 1, action: null});
  assert.deepEqual(L.treeKey(rows, 3, 'ArrowDown'), {focus: 3, action: null});
  assert.deepEqual(L.treeKey(rows, 0, 'ArrowUp'), {focus: 0, action: null});
  assert.deepEqual(L.treeKey(rows, 2, 'Enter'), {focus: 2, action: 'apply'});
  assert.deepEqual(L.treeKey(rows, 3, 'Enter'), {focus: 3, action: 'toggle'});
  assert.deepEqual(L.treeKey(rows, 3, 'ArrowRight'), {focus: 3, action: 'expand'});
  assert.deepEqual(L.treeKey(rows, 0, 'ArrowRight'), {focus: 1, action: null});
  assert.deepEqual(L.treeKey(rows, 0, 'ArrowLeft'), {focus: 0, action: 'collapse'});
  assert.deepEqual(L.treeKey(rows, 2, 'ArrowLeft'), {focus: 0, action: null});
  assert.deepEqual(L.treeKey(rows, 1, 'ArrowLeft'), {focus: 0, action: null});
  assert.deepEqual(L.treeKey(rows, 2, 'ArrowRight'), {focus: 2, action: null});
  assert.deepEqual(L.treeKey(rows, 2, 'Home'), {focus: 0, action: null});
  assert.deepEqual(L.treeKey(rows, 0, 'End'), {focus: 3, action: null});
  assert.equal(L.treeKey(rows, 0, 'x'), null);
});

test('R6: search matches name and group, all terms', () => {
  const p = {name: '16 Cinematic 16', group: '電影 - 青橙'};
  assert.ok(L.matchPreset(p, '電影'));
  assert.ok(L.matchPreset(p, 'cinematic'));
  assert.ok(L.matchPreset(p, 'CINE 青橙'));
  assert.ok(!L.matchPreset(p, 'cinematic 人像'));
  assert.ok(L.matchPreset(p, '  '));
});

test('R6: typed values', () => {
  assert.equal(L.parseValueInput('+12', CONTRAST), 12);
  assert.equal(L.parseValueInput('−30', CONTRAST), -30);   // unicode minus
  assert.equal(L.parseValueInput(' -0.37 ', EXPO), -0.37);
  assert.equal(L.parseValueInput('250', CONTRAST), 100);
  assert.equal(L.parseValueInput('150%', {min: 0, max: 200, step: 1}), 150);
  assert.equal(L.parseValueInput('abc', CONTRAST), null);
  assert.equal(L.parseValueInput('', CONTRAST), null);
});

test('R6: curve at strength', () => {
  const pts = [[0, 20], [128, 140], [255, 240]];
  assert.deepEqual(L.curveAtStrength(pts, 100), pts);
  assert.deepEqual(L.curveAtStrength(pts, 0), [[0, 0], [128, 128], [255, 255]]);
  assert.deepEqual(L.curveAtStrength(pts, 200), [[0, 40], [128, 152], [255, 225]]);
  assert.deepEqual(L.curveAtStrength([[0, 200]], 200), [[0, 255]]);   // clamped to 0..255
  const d = L.curvePath(pts, 100);
  assert.ok(d.startsWith('M0.0 '), d);
  assert.ok(d.includes('L100.0 '), d);
});
