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

// ---------------------------------------------------------------- shared R3 cases (also run by Python, F9)
const CASES = require(path.join(__dirname, '..', 'cases', 'r3_slider_cases.json'));

test('R3 shared cases: sliderView', () => {
  assert.ok(CASES.view.length >= 10);
  for (const c of CASES.view) {
    const v = L.sliderView(CASES.sliders[c.key], c.preset, c.strength, c.tweak);
    assert.ok(Math.abs(v.raw - c.raw) < 1e-9, c.name + ' raw');
    assert.ok(Math.abs(v.base - c.base) < 1e-9, c.name + ' base');
    assert.ok(Math.abs(v.value - c.value) < 1e-9, c.name + ' value');
    assert.equal(v.clamped, c.clamped, c.name + ' clamped');
  }
});

test('R3 shared cases: tweakFor', () => {
  for (const c of CASES.tweak) {
    assert.ok(Math.abs(L.tweakFor(CASES.sliders[c.key], c.preset, c.strength, c.input) - c.tweak) < 1e-9, c.name);
  }
});

// ---------------------------------------------------------------- editor state transitions (F2, R5)
const S_CONTRAST = CASES.sliders.Contrast2012;
const dispatch = (ed, ...actions) => actions.reduce((e, a) => L.reduce(e, a), ed);

test('R5: selecting a preset keeps strength and tweaks', () => {
  let ed = L.initialEditor();
  ed = dispatch(ed, {type: 'selectPreset', id: 'a'}, {type: 'setStrength', value: 150},
                {type: 'setValue', slider: S_CONTRAST, presetValue: 20, value: 40});
  assert.equal(ed.strength, 150);
  assert.deepEqual(ed.tweaks, {Contrast2012: 10});           // 20 x 150% = 30, shown 40 -> +10
  ed = L.reduce(ed, {type: 'selectPreset', id: 'b'});
  assert.equal(ed.presetId, 'b');
  assert.equal(ed.strength, 150);
  assert.deepEqual(ed.tweaks, {Contrast2012: 10});
  ed = L.reduce(ed, {type: 'selectPreset', id: null});
  assert.equal(ed.presetId, null);
  assert.deepEqual(ed.tweaks, {Contrast2012: 10});
});

test('R5: undo / redo walk back through preset, strength, values and resets', () => {
  let ed = dispatch(L.initialEditor(), {type: 'selectPreset', id: 'a'}, {type: 'setStrength', value: 120},
                    {type: 'setValue', slider: S_CONTRAST, presetValue: 0, value: 25},
                    {type: 'selectPreset', id: 'b'}, {type: 'resetAll'});
  assert.deepEqual([ed.presetId, ed.strength, ed.tweaks], ['b', 120, {}]);
  ed = L.reduce(ed, {type: 'undo'});
  assert.deepEqual([ed.presetId, ed.strength, ed.tweaks], ['b', 120, {Contrast2012: 25}]);
  ed = L.reduce(ed, {type: 'undo'});
  assert.deepEqual([ed.presetId, ed.strength, ed.tweaks], ['a', 120, {Contrast2012: 25}]);
  ed = dispatch(ed, {type: 'undo'}, {type: 'undo'});
  assert.deepEqual([ed.presetId, ed.strength, ed.tweaks], ['a', 100, {}]);
  ed = L.reduce(ed, {type: 'undo'});
  assert.deepEqual([ed.presetId, ed.strength, ed.tweaks], [null, 100, {}]);
  assert.equal(L.canUndo(ed), false);
  assert.equal(L.reduce(ed, {type: 'undo'}), ed);             // nothing to undo: same state
  ed = dispatch(ed, {type: 'redo'}, {type: 'redo'});
  assert.deepEqual([ed.presetId, ed.strength], ['a', 120]);
  ed = L.reduce(ed, {type: 'resetKey', key: 'Contrast2012'});  // no tweak there yet at this point: no-op
  assert.equal(L.canRedo(ed), true);
  ed = L.reduce(ed, {type: 'setStrength', value: 90});         // a new change drops the redo branch
  assert.equal(L.canRedo(ed), false);
});

test('R5: one drag is one history step; at least 50 steps kept', () => {
  let ed = L.reduce(L.initialEditor(), {type: 'selectPreset', id: 'a'});
  for (const v of [-10, -20, -30, -40]) {
    ed = L.reduce(ed, {type: 'setValue', slider: S_CONTRAST, presetValue: 0, value: v, gesture: 'Contrast2012'});
  }
  ed = L.reduce(ed, {type: 'endGesture'});
  for (const v of [110, 120, 130]) ed = L.reduce(ed, {type: 'setStrength', value: v, gesture: 'strength'});
  ed = L.reduce(ed, {type: 'endGesture'});
  assert.equal(ed.past.length, 3);                            // select, drag, strength drag
  ed = L.reduce(ed, {type: 'undo'});
  assert.deepEqual([ed.strength, ed.tweaks], [100, {Contrast2012: -40}]);
  ed = L.reduce(ed, {type: 'undo'});
  assert.deepEqual(ed.tweaks, {});
  let e2 = L.reduce(L.initialEditor(), {type: 'selectPreset', id: 'a'});
  for (let i = 1; i <= 70; i++) e2 = L.reduce(e2, {type: 'setStrength', value: i});
  for (let i = 0; i < 50; i++) e2 = L.reduce(e2, {type: 'undo'});
  assert.equal(e2.strength, 20);
  assert.ok(L.HISTORY_LIMIT >= 50);
});

test('R5: strength is disabled and ignored without a preset', () => {
  let ed = L.initialEditor();
  assert.equal(L.strengthEnabled(ed), false);
  const same = L.reduce(ed, {type: 'setStrength', value: 150});
  assert.equal(same.strength, 100);
  assert.equal(same.past.length, 0);
  ed = L.reduce(ed, {type: 'selectPreset', id: 'a'});
  assert.equal(L.strengthEnabled(ed), true);
  ed = L.reduce(ed, {type: 'setStrength', value: 150});
  ed = L.reduce(ed, {type: 'selectPreset', id: null});
  assert.equal(L.strengthInEffect(ed), 100);                   // no preset: tweaks apply at full value
  assert.equal(ed.strength, 150);                              // remembered for the next preset
});

test('R5: tweaks are measured at the strength in effect', () => {
  const ed = L.reduce(L.initialEditor(), {type: 'setValue', slider: S_CONTRAST, presetValue: 0, value: 30});
  assert.deepEqual(ed.tweaks, {Contrast2012: 30});
  const e2 = L.reduce(ed, {type: 'setValue', slider: S_CONTRAST, presetValue: 0, value: 0});
  assert.deepEqual(e2.tweaks, {});                             // back to the base value removes the key
});

test('R5 / F4 / S11: carry-over hint only with a photo, a preset or a tweak, and no edit of this photo yet', () => {
  const ed = L.initialEditor();
  assert.equal(L.carryHintVisible(ed, true, false), false);
  assert.equal(L.carryHintVisible(L.reduce(ed, {type: 'selectPreset', id: 'a'}), false, false), false);
  assert.equal(L.carryHintVisible(L.reduce(ed, {type: 'selectPreset', id: 'a'}), true, false), true);
  assert.equal(L.carryHintVisible(L.reduce(ed, {type: 'selectPreset', id: 'a'}), true, true), false);   // saved: no hint
  const tw = L.reduce(ed, {type: 'setValue', slider: S_CONTRAST, presetValue: 0, value: 30});
  assert.equal(L.carryHintVisible(tw, true, false), true);
  assert.equal(L.carryHintVisible(L.reduce(tw, {type: 'resetAll'}), true, false), false);
  assert.equal(L.CARRY_HINT, '沿用上一張的設定（還不是這張的編輯，會再沿用到下一張）');
  assert.equal(L.CARRY_HINT_SHORT, '沿用中');
});

test('S1 / S2: the autosave request carries the remembered snapshot through paste, else PUT', () => {
  let ed = L.reduce(L.initialEditor(), {type: 'selectPreset', id: 'p'});
  ed = L.reduce(ed, {type: 'setStrength', value: 80});
  ed = L.reduce(ed, {type: 'setValue', slider: S_CONTRAST, presetValue: 0, value: 30});
  const snap = {id: 'p', name: 'n', group: 'g', params: {schema: 'darkroom-params/1', values: {Exposure2012: 1}, curves: {}, masks: [], skipped: []}};
  assert.deepEqual(L.editRequest(ed, 'D:/x.jpg', {}, 'f'),
                   {method: 'PUT', body: {path: 'D:/x.jpg', preset_id: 'p', strength: 80, overrides: {Contrast2012: 30}}});
  assert.deepEqual(L.editRequest(ed, 'D:/x.jpg', {p: snap}, 'f'),
                   {method: 'PASTE', body: {targets: ['D:/x.jpg'], edit: {schema: 'darkroom-edit/1', fingerprint: 'f', preset: snap,
                                                                          strength: 80, overrides: {Contrast2012: 30}}}});
  assert.equal(L.editRequest(ed, 'D:/x.jpg', {q: snap}, 'f').method, 'PUT');              // another preset: library
  assert.equal(L.editRequest(L.reduce(ed, {type: 'selectPreset', id: null}), 'x', {p: snap}, 'f').method, 'PUT');
  assert.equal(L.editRequest(ed, 'x', {p: snap}, null).body.edit.fingerprint, '');
  assert.equal(L.SAVE_RETRY_MS, 2000);
});

test('S3: slider baseline comes from the snapshot; banner and note from the library detail when present', () => {
  const snap = {id: 'p', name: '舊名', group: 'g', params: {schema: 'darkroom-params/1', values: {Exposure2012: 1.0}, curves: {ToneCurvePV2012: [[0, 0], [255, 200]]}, masks: [], skipped: []}};
  const d = L.detailFromSnapshot(snap, {values: {Exposure2012: 0.3}, curves: {}, banner: 'B', note: 'N'});
  assert.deepEqual([d.values, d.curves, d.banner, d.note, d.name, d.snapshot], [{Exposure2012: 1.0}, {ToneCurvePV2012: [[0, 0], [255, 200]]}, 'B', 'N', '舊名', true]);
  const m = L.detailFromSnapshot(snap, null);                                        // missing from the library
  assert.deepEqual([m.values, m.banner, m.note, m.name], [{Exposure2012: 1.0}, '', '', '舊名']);
  assert.notEqual(d.values, snap.params.values);                                      // copies
});

test('S17: drawn-slider variables, hue dots, canvas choice', () => {
  const v = L.sliderView(CONTRAST, 40, 100, 10);                  // base 40, value 50 on -100..100
  assert.deepEqual(L.sliderVars(CONTRAST, v), {base: '70.00%', lo: '70.00%', hi: '75.00%'});
  const w = L.sliderView(CONTRAST, -75, 150, 10);                 // clamped base -100 -> 0 %
  assert.deepEqual(L.sliderVars(CONTRAST, w), {base: '0.00%', lo: '0.00%', hi: '5.00%'});
  assert.deepEqual(L.sliderVars(EXPO, L.sliderView(EXPO, 1, 100, -2)), {base: '60.00%', lo: '40.00%', hi: '60.00%'});
  assert.deepEqual(L.strengthVars(100), {base: '50%', lo: '50.00%', hi: '50.00%'});
  assert.deepEqual(L.strengthVars(150), {base: '50%', lo: '50.00%', hi: '75.00%'});
  assert.deepEqual(L.strengthVars(0), {base: '50%', lo: '0.00%', hi: '50.00%'});
  assert.equal(L.bipolar(CONTRAST), true);
  assert.equal(L.bipolar(GRAIN), false);
  assert.equal(L.hueDot('HueAdjustmentRed'), '#e04848');
  assert.equal(L.hueDot('LuminanceAdjustmentBlue'), '#4a7fe0');
  assert.equal(L.hueDot('Contrast2012'), null);
  assert.deepEqual(L.CANVASES, ['dark', 'black', 'mid']);
  assert.equal(L.CANVAS_STORAGE_KEY, 'darkroom.canvas');
  assert.equal(L.canvasFrom('mid'), 'mid');
  assert.equal(L.canvasFrom('blue'), 'dark');
});

test('S7: A/B split keyboard steps and stored value', () => {
  assert.equal(L.AB_KEY, 'y');
  assert.equal(L.AB_STORAGE_KEY, 'darkroom.abSplit');
  assert.equal(L.AB_DEFAULT_SPLIT, 0.5);
  assert.ok(Math.abs(L.abStep(0.5, 'ArrowLeft', false) - 0.49) < 1e-9);
  assert.ok(Math.abs(L.abStep(0.5, 'ArrowRight', true) - 0.6) < 1e-9);
  assert.equal(L.abStep(0.005, 'ArrowLeft', false), 0);
  assert.equal(L.abStep(0.99, 'ArrowRight', true), 1);
  assert.equal(L.abStep(0.3, 'Home', false), 0);
  assert.equal(L.abStep(0.3, 'End', false), 1);
  assert.equal(L.abStep(0.3, 'a', false), null);
  assert.equal(L.abSplitFrom('0.25'), 0.25);
  assert.equal(L.abSplitFrom(null), 0.5);
  assert.equal(L.abSplitFrom('7'), 0.5);
  assert.equal(L.abSplitFrom('abc'), 0.5);
});

test('S8 / S9 / S10: badge titles, the grid filter, reset / restore sentences and the reducer step', () => {
  assert.equal(L.badgeTitle({preset: '底片 01', strength: 130, status: 'current'}), '底片 01　130%');
  assert.equal(L.badgeTitle({preset: '底片 01', strength: 130, status: 'changed'}), '底片 01　130%（preset 已變更）');
  assert.equal(L.badgeTitle({preset: '底片 01', strength: 80, status: 'missing'}), '底片 01　80%（preset 已不在庫裡）');
  assert.equal(L.badgeTitle({preset: null, strength: 100, status: null}), '只有微調　100%');
  assert.equal(L.badgeTitle(null), '已編輯');
  assert.equal(L.stale({status: 'changed'}), true);
  assert.equal(L.stale({status: 'current'}), false);
  assert.equal(L.stale(null), false);
  const items = [{edited: true}, {edited: false}, {edited: null}, {edited: true}];
  assert.deepEqual(L.gridFilter(items, 'all').shown.map(([i]) => i), [0, 1, 2, 3]);
  assert.equal(L.gridFilter(items, 'all').pending, 0);
  assert.deepEqual(L.gridFilter(items, 'edited').shown.map(([i]) => i), [0, 3]);
  assert.deepEqual(L.gridFilter(items, 'plain').shown.map(([i]) => i), [1]);
  assert.equal(L.gridFilter(items, 'plain').pending, 1);
  assert.deepEqual(L.FILTERS, ['all', 'edited', 'plain']);
  assert.deepEqual(L.FILTER_LABELS, {all: '全部', edited: '已編輯', plain: '未編輯'});
  assert.equal(L.gridPending(3), '還有 3 張尚未判定');
  assert.equal(L.resetConfirm(4), '要把 4 張照片還原成原圖嗎？（可用「取回上一份」拿回來）');
  assert.equal(L.resetDone(3, 1), '已還原 3 張，失敗 1 張');
  assert.equal(L.restoreDone(2, 0), '已取回 2 張，失敗 0 張');
  assert.equal(L.RESET_TOAST, '已還原成原圖（Ctrl+Z 可拿回）');
  assert.equal(L.RESTORE_TOAST, '已取回上一份編輯');
  let ed = L.reduce(L.initialEditor(), {type: 'selectPreset', id: 'p'});
  ed = L.reduce(ed, {type: 'setStrength', value: 140});
  ed = L.reduce(ed, {type: 'setValue', slider: S_CONTRAST, presetValue: 0, value: 30});
  const r = L.reduce(ed, {type: 'resetToOriginal'});
  assert.deepEqual([r.presetId, r.strength, r.tweaks], [null, 140, {}]);       // one step; strength kept
  assert.equal(r.past.length, ed.past.length + 1);
  const u = L.reduce(r, {type: 'undo'});
  assert.deepEqual([u.presetId, u.strength, u.tweaks], ['p', 140, {Contrast2012: 30}]);   // Ctrl+Z brings it back
  const e0 = L.initialEditor();
  assert.equal(L.reduce(e0, {type: 'resetToOriginal'}), e0);                    // nothing to reset: no step
});

test('S14: English service sentences are explained in Chinese, unknown ones pass through', () => {
  assert.equal(L.explain('path is required'), '請輸入照片路徑');
  assert.equal(L.explain('photo not found: D:/a.jpg'), '找不到照片：D:/a.jpg');
  assert.equal(L.explain('unsupported photo format (JPEG/PNG/TIFF/HEIC)'), '不支援的照片格式（只接受 JPEG／PNG／TIFF／HEIC）');
  assert.equal(L.explain('unknown image_id'), '照片已不在記憶體裡，請重新開啟');
  assert.equal(L.explain('unknown preset p1'), '找不到 preset：p1');
  assert.equal(L.explain('unknown or unsupported preset p1'), '找不到或不支援的 preset：p1');
  assert.equal(L.explain('strength must be a number in 0..200'), '強度要在 0～200 之間');
  assert.equal(L.explain('strength must be within 0..200, got 250'), '強度要在 0～200 之間：250');
  assert.equal(L.explain("unknown slider key 'X'"), "未知的滑桿：'X'");
  assert.equal(L.explain('body must be JSON'), '請求格式錯誤（不是 JSON）');
  assert.equal(L.explain('request refused: X-Darkroom header required'), '伺服器拒絕了這個請求：X-Darkroom header required');
  assert.equal(L.explain('照片讀取失敗：a.jpg：壞了'), '照片讀取失敗：a.jpg：壞了');
  assert.equal(L.explain(''), '');
  assert.equal(L.openFailed('a.jpg', '找不到照片：D:/a.jpg'), '開啟失敗：a.jpg：找不到照片：D:/a.jpg');
});

test('R5: a drag whose first event changes nothing still records one step', () => {
  let ed = L.reduce(L.initialEditor(), {type: 'selectPreset', id: 'a'});
  ed = L.reduce(ed, {type: 'setStrength', value: 150});
  const before = ed.past.length;
  // contrast preset -75 at 150% shows -100: the first event (-100) is no change, then the drag moves on
  for (const v of [-100, -95, -90]) {
    ed = L.reduce(ed, {type: 'setValue', slider: S_CONTRAST, presetValue: -75, value: v, gesture: 'c'});
  }
  ed = L.reduce(ed, {type: 'endGesture'});
  assert.equal(ed.past.length, before + 1);
  assert.deepEqual(ed.tweaks, {Contrast2012: 10});
  ed = L.reduce(ed, {type: 'undo'});
  assert.deepEqual(ed.tweaks, {});
  assert.equal(ed.strength, 150);
});

test('X13: export request and messages', () => {
  const req = {image_id: 'i', preset_id: 'p', strength: 150, overrides: {Exposure2012: 0.5}};
  assert.deepEqual(L.exportBody(req, 'jpeg', ''), {items: [{image_id: 'i', preset_id: 'p', strength: 150,
                                                            overrides: {Exposure2012: 0.5}}], format: 'jpeg', quality: 92});
  assert.equal(L.exportBody(req, 'jpeg', ' 80 ').quality, 80);
  assert.equal(L.exportBody(req, 'jpeg', '8x').quality, '8x');            // the server says why
  assert.equal('quality' in L.exportBody(req, 'tiff', '80'), false);      // TIFF: no quality
  assert.equal('dest_dir' in L.exportBody(req, 'jpeg', ''), false);       // XP16: no folder over HTTP
  assert.equal(L.EXPORT_BUSY, '匯出中…');
  assert.equal(L.EXPORT_DEFAULT_QUALITY, 92);
  assert.equal(L.exportMessage({ok: true, source: 'a.jpg', output: 'D:\\p\\darkroom 匯出\\a.jpg'}),
               '已匯出：D:\\p\\darkroom 匯出\\a.jpg');
  assert.equal(L.exportMessage({ok: false, source: 'a.jpg', error: '匯出失敗：a.jpg：壞了'}), '匯出失敗：a.jpg：壞了');
  assert.equal(L.exportFailed('a.jpg', '沒有要匯出的照片'), '匯出失敗：a.jpg：沒有要匯出的照片');
  assert.equal(L.baseName('D:\\x\\y\\IMG_1.HEIC'), 'IMG_1.HEIC');
  assert.equal(L.baseName('/a/b.jpg'), 'b.jpg');
});

test('R3 / F8: tooltip sentence with suffixes is fixed', () => {
  assert.equal(L.sliderTooltip(S_CONTRAST, 40, 100, 10), 'preset × 100% = 40；微調 +10；雙擊＝還原這一項');
  assert.equal(L.sliderTooltip(S_CONTRAST, 80, 150, -5), 'preset × 150% = 120，已到上限 100；微調 -5；雙擊＝還原這一項');
  assert.equal(L.sliderTooltip(S_CONTRAST, 40, 0, 0), 'preset × 0% = 0；雙擊＝還原這一項');
});

test('K19: preset library messages, save body, upload batches', () => {
  assert.equal(L.presetSaved('我的'), '已存成 preset：我的');
  assert.equal(L.importSummary(2, 1), '已匯入 2 個，1 個沒有匯入');
  assert.equal(L.FAV_EMPTY, '還沒有最愛，按 preset 旁的 ☆ 加入');
  assert.equal(L.USER_GROUP, '自存 preset');
  assert.equal(L.groupCreated('電影 - 暖調'), '已建立群組：電影 - 暖調');
  assert.equal(L.favMark(true), '★');
  assert.equal(L.favMark(false), '☆');
  const ed = L.initialEditor();
  assert.equal(L.canSavePreset(ed), false);
  assert.equal(L.canSavePreset(Object.assign({}, ed, {presetId: 'p'})), true);
  assert.equal(L.canSavePreset(Object.assign({}, ed, {tweaks: {Exposure2012: 0.5}})), true);
  assert.deepEqual(L.saveBody({preset_id: 'p', strength: 150, overrides: {Exposure2012: 0.5}}, '名', ''),
                   {name: '名', group: '自存 preset', preset_id: 'p', strength: 150, overrides: {Exposure2012: 0.5}});
  assert.equal(L.saveBody({preset_id: null, strength: 100, overrides: {}}, 'x', 'A - B').group, 'A - B');
  const big = 'x'.repeat(400000);
  const batches = L.uploadBatches([{name: 'a.xmp', data_base64: big}, {name: 'b.xmp', data_base64: big},
                                   {name: 'c.xmp', data_base64: 'y'}]);
  assert.deepEqual(batches.map((b) => b.map((f) => f.name)), [['a.xmp'], ['b.xmp', 'c.xmp']]);
  for (const b of batches) assert.ok(b.reduce((n, f) => n + f.data_base64.length, 0) <= L.UPLOAD_BATCH_CHARS);
  const rep = L.importReport([{ok: true, source: 'a.xmp', id: 'import:a'}, {ok: false, source: 'b.txt', error: '不是 .xmp 檔：b.txt'}]);
  assert.deepEqual(rep, {summary: '已匯入 1 個，1 個沒有匯入', lines: ['已匯入：import:a', '不是 .xmp 檔：b.txt']});
});

test('PL15 / PLP9: restoring a saved edit, autosave body, grid selection, export items, sentences', () => {
  let ed = L.reduce(L.initialEditor(), {type: 'selectPreset', id: 'a'});
  ed = L.reduce(ed, {type: 'setStrength', value: 150});
  assert.equal(ed.past.length, 2);
  const edit = {schema: 'darkroom-edit/1', fingerprint: 'f', preset: {id: 'p', name: 'n', group: 'g', params: {}},
                strength: 80, overrides: {Exposure2012: 0.5}};
  const r = L.reduce(ed, {type: 'restoreEdit', edit});
  assert.deepEqual([r.presetId, r.strength, r.tweaks, r.past, r.future, r.gesture], ['p', 80, {Exposure2012: 0.5}, [], [], null]);
  assert.equal(L.canUndo(r), false);                                   // history starts afresh
  assert.notEqual(r.tweaks, edit.overrides);                            // a copy, not the response object
  const none = L.reduce(ed, {type: 'restoreEdit', edit: {schema: 'darkroom-edit/1', fingerprint: 'f', preset: null, strength: 100, overrides: {}}});
  assert.deepEqual([none.presetId, none.strength, none.tweaks], [null, 100, {}]);
  assert.deepEqual(L.editBody(r, 'D:/x.jpg'), {path: 'D:/x.jpg', preset_id: 'p', strength: 80, overrides: {Exposure2012: 0.5}});
  assert.deepEqual(L.editBody(L.reduce(r, {type: 'selectPreset', id: null}), 'x').strength, 100);   // no preset: 100
  assert.deepEqual(L.editBody(L.reduce(r, {type: 'resetAll'}), 'x').overrides, {});
  assert.equal(L.AUTOSAVE_MS, 500);
  // grid selection: click = only i; Ctrl = toggle; Shift = range from the anchor
  let s = L.gridSelect(new Set(), 2, {}, 0);
  assert.deepEqual([[...s.sel], s.anchor], [[2], 2]);
  s = L.gridSelect(s.sel, 4, {ctrl: true}, s.anchor);
  assert.deepEqual([[...s.sel].sort(), s.anchor], [[2, 4], 4]);
  s = L.gridSelect(s.sel, 2, {ctrl: true}, s.anchor);
  assert.deepEqual([[...s.sel], s.anchor], [[4], 2]);
  s = L.gridSelect(s.sel, 6, {shift: true}, s.anchor);
  assert.deepEqual([[...s.sel].sort(), s.anchor], [[2, 3, 4, 5, 6], 2]);
  s = L.gridSelect(s.sel, 0, {shift: true}, s.anchor);
  assert.deepEqual([...s.sel].sort(), [0, 1, 2]);
  s = L.gridSelect(new Set([5]), 1, {shift: true}, undefined);
  assert.deepEqual([...s.sel].sort(), [0, 1]);                          // anchor defaults to 0
  s = L.gridSelect(s.sel, 7, {}, s.anchor);
  assert.deepEqual([...s.sel], [7]);
  // export items: each photo with its own edit; a failed get_edit counts as failed
  const items = L.exportItems(['a', 'b', 'c'], {a: {fingerprint: 'x', edit, preset_status: 'current'},
                                                b: {fingerprint: 'y', edit: null, preset_status: null}, c: null});
  assert.deepEqual(items, {items: [{path: 'a', preset_id: 'p', strength: 80, overrides: {Exposure2012: 0.5}}, {path: 'b'}], failed: 1});
  assert.equal(L.presetStatusText('changed'), 'preset 已變更，這份編輯用的是當時的 preset 快照');
  assert.equal(L.presetStatusText('missing'), 'preset 已不在庫裡，這份編輯用的是當時的 preset 快照');
  assert.equal(L.presetStatusText('current'), '');
  assert.equal(L.presetStatusText(null), '');
  assert.equal(L.copied('IMG_1.jpg'), '已複製 IMG_1.jpg 的編輯');
  assert.equal(L.pasteConfirm('IMG_1.jpg', 3), '要用 IMG_1.jpg 的編輯取代 3 張照片的編輯嗎？');
  assert.equal(L.pasteDone(2, 1), '已貼上 2 張，失敗 1 張');
  assert.equal(L.exportSelectedDone(3, 0), '已匯出 3 張，失敗 0 張');
  assert.equal(L.gridCount(2, 10), '已選 2／10 張');
});

test('PLP17: the three failure toasts are helpers', () => {
  assert.equal(L.saveEditFailed('500'), '儲存編輯失敗：500');
  assert.equal(L.loadEditFailed('x'), '讀取編輯失敗：x');
  assert.equal(L.loadFolderFailed('找不到照片資料夾：D:/x'), '讀取資料夾失敗：找不到照片資料夾：D:/x');
});
