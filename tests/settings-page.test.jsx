import { it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import SettingsPage from '../src/pages/SettingsPage';
import App from '../src/App';

const settings = { cpuLimit: 50, gpuLimit: 50, memoryLimit: 50, profile: 'balanced' };
function expand() { screen.getByText('Pokročilé nastavení odpovědí').closest('details').open = true; }

it('shows a save failure instead of claiming the profile was saved', async () => {
  render(<SettingsPage settings={settings} onSave={async () => ({ ok: false, message: 'Uložení selhalo' })} />);
  expand(); fireEvent.click(screen.getByRole('button', { name: 'Uložit profil' }));
  expect((await screen.findByRole('alert')).textContent).toBe('Uložení selhalo');
});
it('filters installed apps and opens by registry key without a path input', async () => {
  const open = vi.fn().mockResolvedValue({ ok: true, message: 'Spouštím Blender' });
  render(<SettingsPage settings={settings} onOpenApp={open} applications={[{ key: 'b', title: 'Blender' }, { key: 'v', title: 'VS Code' }]} />);
  fireEvent.change(screen.getByRole('textbox', { name: 'Hledat aplikaci' }), { target: { value: 'blender' } });
  expect(screen.queryByRole('button', { name: 'Otevřít VS Code' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Otevřít Blender' }));
  await screen.findByText('Spouštím Blender');
  expect(open).toHaveBeenCalledWith({ key: 'b', title: 'Blender' });
  expect(screen.queryByPlaceholderText(/cestu/)).toBeNull();
});
it('keeps an unsaved profile when system metadata refreshes, then saves it to Electron', async () => {
  vi.useFakeTimers();
  try {
    const save = vi.fn().mockResolvedValue({ cpuLimit: 70, gpuLimit: 70, memoryLimit: 70, profile: 'focused' });
    window.lunaDesktop = { app: { getMeta: vi.fn().mockResolvedValue({ runtimeSettings: settings }) }, settings: { saveRuntime: save } };
    render(<App />);
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole('button', { name: /Nastavení/ })); expand();
    fireEvent.click(screen.getByRole('button', { name: 'Podrobný' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(screen.getByRole('button', { name: 'Podrobný' }).getAttribute('aria-pressed')).toBe('true');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Uložit profil' })); });
    expect(save).toHaveBeenCalledWith({ cpuLimit: 70, gpuLimit: 70, memoryLimit: 70, profile: 'focused' });
    expect(screen.getByRole('status').textContent).toContain('Profil je uložený');
  } finally { vi.useRealTimers(); }
});
