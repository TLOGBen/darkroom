/**
 * 設定頁：讀設定填表單、來源標示、只送有改的鍵（扁平鍵）、後端錯誤原句顯示在對應欄位、成功時顯示重測結果。
 * fetch 換成假的伺服器（形狀照 plan-v2 §3 與後端 darkroom_app/domain/settings.py）。
 */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ThemeProvider } from '@mui/material';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import theme from '../../styles/theme';
import { queryClient } from '../../hooks/queries';
import { SettingsPage } from '../SettingsPage';

const SETTINGS = {
  settings: {
    language: 'zh-TW',
    preset_dir: 'D:/presets/xmp',
    preset_library_dir: null,
    data_dir: null,
    localllms_root: null,
    comfyui_url: 'http://127.0.0.1:8188',
    comfyui_root: null,
    'agent.api_key_ref': null,
    'agent.model': 'claude-haiku-5-5',
    'agent.budget_usd': 5,
    calibration_sources_dir: null,
  },
  defaults: { language: 'zh-TW', comfyui_url: 'http://127.0.0.1:8188', 'agent.model': 'claude-haiku-5-5', 'agent.budget_usd': 5 },
  sources: { language: 'default', preset_dir: 'file', comfyui_url: 'default', 'agent.model': 'env' },
  config_file: 'D:/x/config.local.json',
};

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function renderPage() {
  return render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

describe('SettingsPage', () => {
  let puts: unknown[];
  let putAnswer: () => Response;
  beforeEach(() => {
    queryClient.clear();
    puts = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        if (url === '/api/settings' && init.method === 'PUT') {
          puts.push(JSON.parse(init.body as string));
          return putAnswer();
        }
        if (url === '/api/settings') return json(200, SETTINGS);
        if (url === '/api/version') return json(200, { version: '0.1.0', python: '3.13', torch: null, cuda: null, platform: 'Windows' });
        if (url.startsWith('/api/capabilities')) return json(200, { features: {} });
        return json(404, { error: 'nope' });
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  test('fills the form, marks sources, env fields are read only, the key note is there', async () => {
    renderPage();
    const presetDir = await screen.findByDisplayValue('D:/presets/xmp');
    expect(presetDir).toBeEnabled();
    expect(screen.getByDisplayValue('claude-haiku-5-5')).toBeDisabled(); // 來自環境變數
    expect(screen.getAllByText('來自設定檔').length).toBeGreaterThan(0);
    expect(screen.getByText('金鑰不會存進設定檔：這裡只存 1Password 參照')).toBeInTheDocument();
    expect(screen.getByText('D:/x/config.local.json')).toBeInTheDocument();
  });

  test('a pasted key is refused before anything is sent', async () => {
    renderPage();
    await screen.findByDisplayValue('D:/presets/xmp');
    const ref = document.getElementById('set-agent.api_key_ref') as HTMLInputElement;
    fireEvent.change(ref, { target: { value: 'sk-ant-secret' } });
    fireEvent.click(screen.getByRole('button', { name: '套用' }));
    expect(await screen.findByText(/只接受 1Password 參照/)).toBeInTheDocument();
    expect(puts).toEqual([]);
  });

  test('only changed keys are sent (flat); the backend sentence lands on its field', async () => {
    putAnswer = () => json(400, { error: 'preset_dir 指定的資料夾不存在：D:/nope' });
    renderPage();
    const presetDir = await screen.findByDisplayValue('D:/presets/xmp');
    fireEvent.change(presetDir, { target: { value: 'D:/nope' } });
    fireEvent.click(screen.getByRole('button', { name: '套用' }));
    expect(await screen.findByText('preset_dir 指定的資料夾不存在：D:/nope')).toBeInTheDocument();
    expect(puts).toEqual([{ values: { preset_dir: 'D:/nope' } }]);
  });

  test('success shows each check result', async () => {
    putAnswer = () =>
      json(200, {
        settings: { ...SETTINGS.settings, comfyui_url: 'http://127.0.0.1:8190' },
        applied: ['comfyui_url'],
        checks: { comfyui: { available: false, reason: '連不到 ComfyUI（http://127.0.0.1:8190）：timed out' } },
      });
    renderPage();
    const url = await screen.findByDisplayValue('http://127.0.0.1:8188');
    fireEvent.change(url, { target: { value: 'http://127.0.0.1:8190' } });
    fireEvent.click(screen.getByRole('button', { name: '套用' }));
    await waitFor(() => expect(puts).toEqual([{ values: { comfyui_url: 'http://127.0.0.1:8190' } }]));
    expect(await screen.findByText(/連不到 ComfyUI（http:\/\/127\.0\.0\.1:8190）：timed out/)).toBeInTheDocument();
  });
});
