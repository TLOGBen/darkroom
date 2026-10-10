/**
 * preset 樹（role="tree"）：第一列「（不套 preset，只用微調）」，接著「★ 最愛」，再來是群組樹（第一個「 - 」分上下層）；
 * 搜尋時改成平的結果清單（每列附群組路徑）。
 *
 * 行為照舊 app.js（R4 旗標、R6 鍵盤、K19 最愛與動作選單、SI10 語意標籤的提示）：
 *   - 點 preset＝套用（強度與微調保留）；不支援的 preset 點不了。
 *   - 鍵盤：↑↓ Home End 移動、→ 展開／進入、← 收起／回上層、Enter 套用或切換；roving tabindex（Tab 只進得到一列）。
 *   - 星號＝最愛、「⋯」＝改名／搬到／新群組／下載 .xmp；平常半透明，滑過或焦點才全亮。
 *   - 「整理 preset 庫」關閉時，最愛與寫入的選單項目停用、提示寫原因（E20）。
 * 資料：presets／flags／groups 來自 TanStack Query；目前的 preset 來自 useEditStore；展開與焦點在 usePresetStore。
 */
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react';
import { Menu, MenuItem } from '@mui/material';
import clsx from 'clsx';
import {
  UNGROUPED,
  buildTree,
  favMark,
  matchPreset,
  presetTitle,
  treeKey,
  type Preset,
  type TreeRowMeta,
} from '../../domain/preset';
import { capReason } from '../../domain/settings';
import { useCapabilities, usePresetFlags, usePresetGroups, usePresets } from '../../hooks/queries';
import { useEditStore } from '../../hooks/useEditStore';
import { FAV_KEY, usePresetStore } from '../../hooks/usePresetStore';
import { useT } from '../../hooks/useT';
import css from './PresetTree.module.scss';

interface Row extends TreeRowMeta {
  key: string;
  /** 資料夾的展開鍵 */
  fkey?: string;
  label: string;
  count?: number;
  /** 群組的完整路徑（給群組選單）；最愛與未分組沒有 */
  path?: string | null;
  preset?: Preset | null;
  showPath?: boolean;
  /** 這列之前要插的說明（「找到 N 個」、最愛是空的） */
  before?: string;
  after?: string;
}

export function PresetTree() {
  const t = useT();
  const { data: presets = [] } = usePresets();
  const { data: flags = {} } = usePresetFlags();
  const { data: groups } = usePresetGroups();
  const { data: caps } = useCapabilities();
  const presetId = useEditStore((s) => s.ed.presetId);
  const search = usePresetStore((s) => s.search.trim());
  const openFolders = usePresetStore((s) => s.openFolders);
  const focusKey = usePresetStore((s) => s.focusKey);
  const boxRef = useRef<HTMLDivElement>(null);
  const [menu, setMenu] = useState<{ anchor: HTMLElement; row: Row } | null>(null);
  const writesOff = capReason(caps ?? null, 'preset_library_writes');

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    const add = (r: Row) => {
      out.push(r);
      return out.length - 1;
    };
    add({ key: 'p:', type: 'preset', depth: 0, parent: -1, label: t('presets.none'), preset: null });
    if (search) {
      const hits = presets.filter((p) => matchPreset(p, search));
      hits.forEach((p, i) =>
        add({
          key: 'p:' + p.id,
          type: 'preset',
          depth: 0,
          parent: -1,
          label: p.name,
          preset: p,
          showPath: true,
          before: i === 0 ? t('presets.found', { n: hits.length }) : undefined,
        }),
      );
      if (!hits.length) out[0].after = t('presets.found', { n: 0 });
      return out;
    }
    const favs = presets.filter((p) => p.favorite);
    const favIdx = add({
      key: 'f:' + FAV_KEY,
      fkey: FAV_KEY,
      type: 'folder',
      depth: 0,
      open: !!openFolders[FAV_KEY],
      parent: -1,
      label: t('presets.favorites'),
      count: favs.length,
      path: null,
    });
    if (openFolders[FAV_KEY]) {
      if (!favs.length) out[favIdx].after = t('presets.favEmpty');
      favs.forEach((p) =>
        add({ key: 'p:\u0001' + p.id, type: 'preset', depth: 1, parent: favIdx, label: p.name, preset: p, showPath: true }),
      );
    }
    for (const [top, node] of buildTree(presets, groups)) {
      const count = node.items.length + [...node.subs.values()].reduce((a, l) => a + l.length, 0);
      const topIdx = add({
        key: 'f:' + top,
        fkey: top,
        type: 'folder',
        depth: 0,
        open: !!openFolders[top],
        parent: -1,
        label: top === UNGROUPED ? t('presets.ungrouped') : top,
        count,
        path: top === UNGROUPED ? null : top,
      });
      if (!openFolders[top]) continue;
      for (const [sub, list] of node.subs) {
        const key = top + '\u0000' + sub;
        const subIdx = add({
          key: 'f:' + key,
          fkey: key,
          type: 'folder',
          depth: 1,
          open: !!openFolders[key],
          parent: topIdx,
          label: sub,
          count: list.length,
          path: top + ' - ' + sub,
        });
        if (openFolders[key])
          list.forEach((p) => add({ key: 'p:' + p.id, type: 'preset', depth: 2, parent: subIdx, label: p.name, preset: p }));
      }
      node.items.forEach((p) => add({ key: 'p:' + p.id, type: 'preset', depth: 1, parent: topIdx, label: p.name, preset: p }));
    }
    return out;
  }, [presets, groups, openFolders, search, t]);

  // roving tabindex：剛好一列 Tab 進得去——鍵盤焦點列，否則目前的 preset，否則第一列
  let tabIndexRow = rows.findIndex((r) => r.key === focusKey);
  if (tabIndexRow < 0) tabIndexRow = rows.findIndex((r) => r.type === 'preset' && (r.preset?.id ?? null) === presetId);
  if (tabIndexRow < 0) tabIndexRow = 0;

  const pendingFocus = useRef<string | null>(null);
  useEffect(() => {
    if (!pendingFocus.current) return;
    const el = boxRef.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(pendingFocus.current)}"]`);
    pendingFocus.current = null;
    el?.focus();
    el?.scrollIntoView({ block: 'nearest' });
  });

  const store = usePresetStore.getState;
  const apply = (r: Row) => {
    store().setFocusKey(r.key);
    void useEditStore.getState().selectPreset(r.preset ? r.preset.id : null);
  };
  const toggle = (r: Row, open?: boolean) => {
    store().setFocusKey(r.key);
    store().setOpen(r.fkey as string, open ?? !openFolders[r.fkey as string]);
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>('[data-row]');
    if (!el) return;
    const i = Number(el.dataset.row);
    const res = treeKey(rows, i, e.key);
    if (!res) return;
    e.preventDefault();
    const target = rows[res.focus];
    if (res.action === 'apply') {
      if (!target.preset || target.preset.supported) {
        apply(target);
        pendingFocus.current = target.key;
      }
      return;
    }
    if (res.action) {
      toggle(target, res.action === 'expand' ? true : res.action === 'collapse' ? false : undefined);
      pendingFocus.current = target.key;
      return;
    }
    store().setFocusKey(target.key);
    pendingFocus.current = target.key;
  };

  const openMenu = (e: MouseEvent<HTMLButtonElement>, row: Row) => {
    e.stopPropagation();
    setMenu({ anchor: e.currentTarget, row });
  };

  const flag = (p: Preset) => {
    if (!p.supported) return <span className={clsx(css.flag, css.major)} title={t('presets.flagUnsupported')}>⛔</span>;
    const lv = flags[p.id];
    if (lv === 'major') return <span className={clsx(css.flag, css.major)} title={t('presets.flagMajor')}>⚠</span>;
    if (lv === 'minor') return <span className={clsx(css.flag, css.minor)} title={t('presets.flagMinor')}>·</span>;
    return null;
  };

  return (
    <div className={css.tree} role="tree" aria-label={t('presets.libraryTitle')} ref={boxRef} onKeyDown={onKey}>
      {rows.map((r, i) => {
        const pad = { paddingLeft: 6 + r.depth * 14 };
        const common = {
          'data-row': i,
          'data-key': r.key,
          tabIndex: i === tabIndexRow ? 0 : -1,
          role: 'treeitem',
          'aria-level': r.depth + 1,
          onFocus: () => store().setFocusKey(r.key),
        };
        return (
          <Fragment key={r.key}>
            {r.before && <div className={css.secTitle}>{r.before}</div>}
            {r.type === 'folder' ? (
              <div {...common} aria-expanded={!!r.open} className={clsx(css.node, css.folder)} style={pad} onClick={() => toggle(r)}>
                <span className={clsx(css.tw, r.open && css.twOpen)} aria-hidden="true">
                  ▶
                </span>
                <span className={css.nm}>{r.label}</span>
                <span className={css.cnt}>{r.count}</span>
                {r.path && (
                  <>
                    <span className={css.sp} />
                    <button
                      type="button"
                      tabIndex={-1}
                      className={css.act}
                      title={t('presets.groupMenu')}
                      aria-label={t('presets.groupMenu')}
                      aria-haspopup="menu"
                      onClick={(e) => openMenu(e, r)}
                    >
                      ⋯
                    </button>
                  </>
                )}
              </div>
            ) : (
              <div
                {...common}
                aria-selected={(r.preset?.id ?? null) === presetId}
                className={clsx(
                  css.node,
                  css.preset,
                  (r.preset?.id ?? null) === presetId && css.active,
                  r.preset && !r.preset.supported && css.unsupported,
                )}
                style={pad}
                title={r.preset ? presetTitle(r.preset) : undefined}
                onClick={() => {
                  if (!r.preset || r.preset.supported) apply(r);
                }}
              >
                <span className={css.tw} />
                <span className={css.nm}>{r.label}</span>
                {r.preset && flag(r.preset)}
                {r.showPath && r.preset && <span className={css.path}>{r.preset.group}</span>}
                {r.preset && (
                  <>
                    <span className={css.sp} />
                    <button
                      type="button"
                      tabIndex={-1}
                      className={clsx(css.act, css.fav, r.preset.favorite && css.favOn)}
                      aria-pressed={!!r.preset.favorite}
                      disabled={writesOff !== null}
                      title={writesOff ?? (r.preset.favorite ? t('presets.removeFavorite') : t('presets.addFavorite'))}
                      aria-label={r.preset.favorite ? t('presets.removeFavorite') : t('presets.addFavorite')}
                      onClick={(e) => {
                        e.stopPropagation();
                        void store().toggleFavorite(r.preset as Preset);
                      }}
                    >
                      {favMark(r.preset.favorite)}
                    </button>
                    <button
                      type="button"
                      tabIndex={-1}
                      className={css.act}
                      title={t('presets.rowMenu')}
                      aria-label={t('presets.rowMenu')}
                      aria-haspopup="menu"
                      onClick={(e) => openMenu(e, r)}
                    >
                      ⋯
                    </button>
                  </>
                )}
              </div>
            )}
            {r.after && <div className={css.empty}>{r.after}</div>}
          </Fragment>
        );
      })}
      <Menu
        open={!!menu}
        anchorEl={menu?.anchor}
        onClose={() => setMenu(null)}
        slotProps={{ list: { dense: true } }}
      >
        {menu &&
          (menu.row.type === 'preset' && menu.row.preset
            ? [
                ['rename', t('presets.menu.rename'), () => store().rename(menu.row.preset as Preset), writesOff],
                ['move', t('presets.menu.move'), () => store().move(menu.row.preset as Preset), writesOff],
                ['group', t('presets.menu.newGroup'), () => store().newGroup((menu.row.preset as Preset).group), writesOff],
                ['dl', t('presets.menu.download'), () => store().downloadPresets([(menu.row.preset as Preset).id]), null],
              ]
            : [
                ['rename', t('presets.menu.renameGroup'), () => store().renameGroup(menu.row.path as string), writesOff],
                ['group', t('presets.menu.newGroup'), () => store().newGroup(menu.row.path as string), writesOff],
                ['dl', t('presets.menu.downloadGroup'), () => store().downloadGroup(menu.row.path as string), null],
              ]
          ).map(([k, label, run, off]) => (
            <MenuItem
              key={k as string}
              disabled={off !== null}
              title={(off as string | null) ?? undefined}
              onClick={() => {
                setMenu(null);
                void (run as () => Promise<void>)();
              }}
            >
              {label as string}
            </MenuItem>
          ))}
      </Menu>
    </div>
  );
}
