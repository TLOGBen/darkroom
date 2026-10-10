/**
 * toast：底部置中、反轉色；錯誤是紅底（DESIGN.md §6.6）。可以帶一顆動作鈕（例如「復原」）。
 * 內容來自 hooks/useAppStore 的 `toast`；後端原句被說明成看得懂的句子時，原句放在 title（滑過看得到）。
 */
import { Button, Snackbar, SnackbarContent } from '@mui/material';
import { useAppStore } from '../../hooks/useAppStore';

export function ToastHost() {
  const toast = useAppStore((s) => s.toast);
  const hide = useAppStore((s) => s.hideToast);
  return (
    <Snackbar
      key={toast?.id}
      open={!!toast}
      autoHideDuration={toast?.ms ?? 2600}
      onClose={(_, reason) => {
        if (reason !== 'clickaway') hide();
      }}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
    >
      <SnackbarContent
        role="status"
        title={toast?.title ?? toast?.text}
        message={toast?.text}
        sx={toast?.err ? { backgroundColor: 'var(--dr-err)', color: 'var(--dr-on-err)' } : undefined}
        action={
          toast?.action ? (
            <Button
              size="small"
              variant="text"
              sx={{ color: 'inherit', textDecoration: 'underline', height: 22 }}
              onClick={() => {
                const run = toast.action?.run;
                hide();
                void run?.();
              }}
            >
              {toast.action.label}
            </Button>
          ) : undefined
        }
      />
    </Snackbar>
  );
}
