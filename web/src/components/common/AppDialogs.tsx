/**
 * 全 App 共用的「問一句話」對話框：取代舊版的瀏覽器 prompt()／confirm()。
 * 狀態在 hooks/useAppStore 的 `dialog`（呼叫端 `await ask(...)`／`await confirmAsk(...)`），這裡只負責畫與回答。
 * DESIGN.md §6.4：一顆主要按鈕在右、取消在左；危險動作用紅色實心並寫清楚刪什麼。
 */
import { useEffect, useState } from 'react';
import { Button, Dialog, DialogActions, DialogContent, DialogTitle, TextField } from '@mui/material';
import { useT } from '../../hooks/useT';
import { useAppStore } from '../../hooks/useAppStore';

export function AppDialogs() {
  const t = useT();
  const dialog = useAppStore((s) => s.dialog);
  const close = useAppStore((s) => s.closeDialog);
  const [value, setValue] = useState('');

  useEffect(() => {
    if (dialog?.kind === 'prompt') setValue(dialog.initial ?? '');
  }, [dialog]);

  if (!dialog) return null;
  const submit = () => close(dialog.kind === 'prompt' ? value : '');

  return (
    <Dialog open onClose={() => close(null)} fullWidth>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <DialogTitle>{dialog.title}</DialogTitle>
        {dialog.kind === 'prompt' && (
          <DialogContent>
            <TextField
              autoFocus
              fullWidth
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onFocus={(e) => e.target.select()}
              slotProps={{ htmlInput: { 'aria-label': dialog.label ?? dialog.title, spellCheck: false } }}
            />
          </DialogContent>
        )}
        <DialogActions>
          <Button onClick={() => close(null)}>{t('common.cancel')}</Button>
          <Button type="submit" variant="contained" color={dialog.danger ? 'error' : 'primary'} autoFocus={dialog.kind === 'confirm'}>
            {dialog.confirmLabel ?? t('common.ok')}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
