/**
 * 有圖示也有文字的工具列按鈕。窄視窗（≤960）時文字縮進 aria-label 與 tooltip，按鈕只剩圖示但「不藏」（DESIGN.md §5）。
 * `pressed` 有給時是切換鈕（aria-pressed，按下＝選取色）。停用時 title 寫原因（S2 E23：功能關閉＝停用＋原因，永遠不藏）。
 */
import { forwardRef, type ReactNode } from 'react';
import { Button, Tooltip, useMediaQuery, type ButtonProps } from '@mui/material';
import { Icon, type IconName } from './Icon';

interface Props extends Omit<ButtonProps, 'title'> {
  icon?: IconName;
  label: ReactNode;
  title?: string;
  pressed?: boolean;
  /** 只有窄視窗才縮成圖示（預設 true） */
  collapsible?: boolean;
}

export const ToolButton = forwardRef<HTMLButtonElement, Props>(function ToolButton(
  { icon, label, title, pressed, collapsible = true, ...rest },
  ref,
) {
  const narrow = useMediaQuery('(max-width: 960px)');
  const iconOnly = narrow && collapsible && !!icon;
  const button = (
    <Button
      ref={ref}
      {...rest}
      aria-pressed={pressed === undefined ? undefined : pressed}
      aria-label={iconOnly && typeof label === 'string' ? label : rest['aria-label']}
      startIcon={icon && !iconOnly ? <Icon name={icon} /> : undefined}
      sx={iconOnly ? { width: 26, px: 0 } : undefined}
    >
      {iconOnly ? <Icon name={icon as IconName} /> : label}
    </Button>
  );
  if (!title) return button;
  // 停用的按鈕收不到滑鼠事件：包一層 span，提示（原因）仍然看得到
  return (
    <Tooltip title={title}>
      <span style={{ display: 'inline-flex' }}>{button}</span>
    </Tooltip>
  );
});
