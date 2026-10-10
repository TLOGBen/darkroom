/**
 * 狀態列存的是「怎麼翻」（函式），切換語言後同一則狀態要跟著換成新語言，不能殘留舊語言的字。
 */
import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import i18n from '../../../i18n';
import { useAppStore } from '../../../hooks/useAppStore';
import { StatusLine } from '../StatusBar';

describe('StatusLine', () => {
  afterEach(async () => {
    await act(() => i18n.changeLanguage('zh-TW'));
  });

  it('re-translates the current status when the language changes', async () => {
    useAppStore.getState().setStatus({ text: (t) => t('status.updated'), cls: 'idle' });
    render(<StatusLine />);
    expect(screen.getByRole('status').textContent).toContain('已更新');
    await act(() => i18n.changeLanguage('en-US'));
    expect(screen.getByRole('status').textContent).toContain('Updated');
    expect(screen.getByRole('status').textContent).not.toContain('已更新');
  });
});
