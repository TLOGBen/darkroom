/**
 * 批次動作的結果面板（匯入 xmp、下載 .xmp、縮圖格的貼上／還原／取回／匯出）：一行摘要＋每筆一行，可以關掉。
 * S13 (b)：每一筆失敗都留在畫面上看得到，不只一個數字。
 */
import { IconButton } from '@mui/material';
import { useT } from '../../hooks/useT';
import { Icon } from './Icon';
import css from './ResultPanel.module.scss';

export function ResultPanel({
  summary,
  lines,
  onClose,
}: {
  summary: string;
  lines: Array<{ ok: boolean; text: string }>;
  onClose: () => void;
}) {
  const t = useT();
  return (
    <div className={css.panel} role="status">
      <div className={css.head}>
        <span>{summary}</span>
        <IconButton aria-label={t('common.close')} title={t('common.close')} onClick={onClose}>
          <Icon name="close" />
        </IconButton>
      </div>
      {lines.map((l, i) => (
        <div key={i} className={l.ok ? css.ok : css.err}>
          {l.text}
        </div>
      ))}
    </div>
  );
}
