import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import App from '../src/App';
import MessageContent from '../src/components/MessageContent';

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup(send = vi.fn()) {
  window.lunaDesktop = { luna: { sendMessage: send }, files: { getPathForFile: vi.fn(() => 'C:\\fixtures\\note.txt') } };
  const view = render(<App />);
  return { ...view, input: screen.getByRole('textbox', { name: 'Zpráva pro Lunu' }), send };
}
function type(input, value) { fireEvent.change(input, { target: { value } }); }
function sendClick() { fireEvent.click(screen.getByRole('button', { name: 'Odeslat' })); }

describe('Chat request lifecycle', () => {
  it('keeps the next draft and attachment after an earlier response arrives', async () => {
    const pending = deferred();
    const { input, send, container } = setup(vi.fn(() => pending.promise));
    type(input, 'První zpráva');
    sendClick();
    expect(input.value).toBe('');
    expect(screen.getByRole('button', { name: 'Čekej…' }).disabled).toBe(true);
    expect(screen.getByText('První zpráva')).toBeTruthy();
    type(input, 'Další rozepsaná zpráva');
    const file = new File(['obsah'], 'note.txt', { type: 'text/plain' });
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [file] } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(send).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve({ ok: true, messages: [], currentChatId: send.mock.calls[0][0].chatId }));
    expect(input.value).toBe('Další rozepsaná zpráva');
    expect(screen.getByText('note.txt')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Odeslat' }).disabled).toBe(false);
  });

  it('sends a selected File through the preload path API even without File.path', async () => {
    const { input, send, container } = setup(vi.fn().mockResolvedValue({ ok: true }));
    const file = new File(['ahoj'], 'note.txt', { type: 'text/plain' });
    expect(file.path).toBeUndefined();
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [file] } });
    type(input, 'Přečti soubor');
    sendClick();
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    expect(window.lunaDesktop.files.getPathForFile).toHaveBeenCalledWith(file);
    expect(send.mock.calls[0][0].filePaths).toEqual(['C:\\fixtures\\note.txt']);
  });

  it('shows a file error instead of pretending an unreadable attachment is ready', () => {
    const { container } = setup();
    window.lunaDesktop.files.getPathForFile.mockReturnValue('');
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [new File(['x'], 'x.txt')] } });
    expect(screen.getByRole('alert').textContent).toContain('Soubor se nepodařilo přiložit');
    expect(screen.queryByRole('button', { name: 'Odebrat přílohu' })).toBeNull();
  });

  it('keeps text intact and shows an honest error when the desktop bridge is absent', () => {
    render(<App />);
    const input = screen.getByRole('textbox', { name: 'Zpráva pro Lunu' });
    type(input, 'Ahoj');
    sendClick();
    expect(input.value).toBe('Ahoj');
    expect(screen.getByRole('alert').textContent).toContain('Připojení k Luně není dostupné');
    expect(screen.queryByText(/shell accepted/)).toBeNull();
  });

  it('restores a failed request for editing without sending it automatically', async () => {
    const { input, send } = setup(vi.fn().mockRejectedValue(new Error('offline')));
    type(input, 'Důležitá zpráva');
    sendClick();
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'Vrátit zprávu k úpravě' }));
    expect(input.value).toBe('Důležitá zpráva');
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('does not overwrite a new draft when the previous request fails', async () => {
    const pending = deferred();
    const { input } = setup(vi.fn(() => pending.promise));
    type(input, 'Původní'); sendClick(); type(input, 'Rozpracovaná');
    await act(async () => pending.resolve({ ok: false, message: 'Model není dostupný.' }));
    expect(screen.getByRole('alert').textContent).toContain('Model není dostupný.');
    expect(input.value).toBe('Rozpracovaná');
    expect(screen.getByRole('button', { name: 'Vrátit zprávu k úpravě' }).disabled).toBe(true);
  });

  it('does not send empty input or an IME composition Enter', () => {
    const { input, send } = setup();
    expect(screen.getByRole('button', { name: 'Odeslat' }).disabled).toBe(true);
    type(input, '文字');
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
    expect(send).not.toHaveBeenCalled();
  });
});

describe('Readable and safe message rendering', () => {
  it('renders headings, lists, tables and code', () => {
    render(<MessageContent content={'## Nadpis\n\n- jeden\n- dva\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```js\nconst x = 1;\n```'} />);
    expect(screen.getByRole('heading', { name: 'Nadpis' })).toBeTruthy();
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByRole('table')).toBeTruthy();
    expect(screen.getByText('const x = 1;')).toBeTruthy();
  });

  it('blocks executable links, raw HTML and automatic remote images', () => {
    const { container } = render(<MessageContent content={'[zlé](javascript:alert%281%29)\n\n<script>alert(1)</script>\n\n![tracker](https://example.com/pixel.png)'} />);
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
  });

  it('opens HTTPS links through Electron', () => {
    window.lunaDesktop = { shell: { openExternal: vi.fn().mockResolvedValue() } };
    render(<MessageContent content={'[Dokumentace](https://example.com/docs)'} />);
    fireEvent.click(screen.getByRole('link', { name: 'Dokumentace' }));
    expect(window.lunaDesktop.shell.openExternal).toHaveBeenCalledWith('https://example.com/docs');
  });
});

it('completes action confirmation and releases the composer after animation removal', async () => {
  const state = { ok: true, currentChatId: 'action-chat', chats: [{ id: 'action-chat', title: 'Test' }], messages: [{ id: 'a1', role: 'assistant', content: 'Potvrď akci.' }] };
  window.lunaDesktop = { luna: {
    getState: vi.fn().mockResolvedValue({ ...state, pendingAction: { active: true, title: 'Testovací akce' } }),
    confirmPendingAction: vi.fn().mockResolvedValue({ ...state, pendingAction: { active: false } }),
  } };
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: 'Potvrdit' }));
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Potvrdit' })).toBeNull());
  type(screen.getByRole('textbox', { name: 'Zpráva pro Lunu' }), 'Další zpráva');
  expect(screen.getByRole('button', { name: 'Odeslat' }).disabled).toBe(false);
});
