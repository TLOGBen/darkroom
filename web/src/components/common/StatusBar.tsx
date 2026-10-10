/**
 * 頂列最右的狀態列（DESIGN.md §6.6）：6px 點＋一行字。閒置點灰、忙碌點亮、錯誤點與字用 clamp 色。
 * 毫秒數等細節放在 title（滑過看得到），不佔版面。內容來自 hooks/useAppStore 的 `status`。
 * 還有能力偵測的按鈕（S2 E30）：「功能正常」或「功能狀態：N 項關閉」，點開列出每一項與原因、可以重新偵測。
 */
import { useEffect, useRef, useState } from 'react';
import { Button, Popover } from '@mui/material';
import { useT } from '../../hooks/useT';
import { CAP_ORDER, capButtonText, capLine, capOff } from '../../domain/settings';
import { explain } from '../../domain/errors';
import { useAppStore, toast } from '../../hooks/useAppStore';
import { refreshCapabilities, useCapabilities } from '../../hooks/queries';
import css from './StatusBar.module.scss';

export function StatusLine() {
  const t = useT();
  const status = useAppStore((s) => s.status);
  // 狀態存的是「怎麼翻」：切換語言時這一行跟著換
  const text = (typeof status.text === 'function' ? status.text(t) : status.text) || t('status.idle');
  const title = typeof status.title === 'function' ? status.title(t) : status.title;
  return (
    <span className={css.status} data-cls={status.cls} title={title ?? text} role="status" aria-live="polite">
      <i className={css.dot} aria-hidden="true" />
      <span className={css.text}>{text}</span>
    </span>
  );
}

export function CapabilitiesButton() {
  const t = useT();
  const { data: caps } = useCapabilities();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [busy, setBusy] = useState(false);
  const refreshRef = useRef<HTMLButtonElement>(null);
  const off = capOff(caps ?? null).length > 0;

  useEffect(() => {
    if (anchor) setTimeout(() => refreshRef.current?.focus(), 0);
  }, [anchor]);

  return (
    <>
      <Button
        variant="text"
        className={off ? css.capOff : undefined}
        title={t('caps.buttonTitle')}
        aria-haspopup="dialog"
        aria-expanded={!!anchor}
        onClick={(e) => setAnchor(anchor ? null : e.currentTarget)}
      >
        {capButtonText(caps ?? null, t)}
      </Button>
      <Popover
        open={!!anchor}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { role: 'dialog', 'aria-label': t('caps.title') } }}
      >
        <div className={css.capBox}>
          <div className={css.capHead}>
            <span>{t('caps.title')}</span>
            <Button
              ref={refreshRef}
              title={t('caps.refreshTitle')}
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await refreshCapabilities();
                } catch (e) {
                  toast(explain((e as Error).message, t), true, (e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {t('caps.refresh')}
            </Button>
          </div>
          <ul className={css.capList}>
            {CAP_ORDER.filter((k) => caps?.[k]).map((k) => (
              <li key={k} className={caps?.[k]?.available ? css.ok : css.off}>
                {capLine(k, caps?.[k], t)}
              </li>
            ))}
          </ul>
        </div>
      </Popover>
    </>
  );
}
