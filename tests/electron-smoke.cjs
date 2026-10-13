// Real Electron preload + production renderer; isolated files and mocked backend.
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'pgex-chat-test-'));
app.setPath('userData', path.join(sandbox, 'profile'));
app.disableHardwareAcceleration();
const root = path.resolve(__dirname, '..');
let win;
let request;
let finishRequest;
const deadline = setTimeout(() => { console.error('Electron smoke test timed out'); app.exit(1); }, 30000);

async function until(check) {
  for (let i = 0; i < 200; i++) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  throw new Error('Expected renderer state was not reached');
}

app.whenReady().then(async () => {
  const fixture = path.join(sandbox, 'attachment.txt');
  fs.writeFileSync(fixture, 'PGEX-ATTACHMENT-7429');
  ipcMain.handle('app:get-meta', () => ({ version: 'test' }));
  ipcMain.handle('apps:list', () => []);
  ipcMain.handle('updates:prepare', () => ({ entries: [], updateAvailable: false }));
  ipcMain.handle('action-engine:get-pending', () => ({ ok: true }));
  ipcMain.handle('luna:get-state', () => ({ ok: true, chats: [], messages: [], currentChatId: '' }));
  ipcMain.handle('luna:send-message', (_, payload) => {
    request = payload;
    return new Promise(resolve => { finishRequest = resolve; });
  });
  win = new BrowserWindow({ show: false, webPreferences: { backgroundThrottling: false, preload: path.join(root, 'electron/preload.cjs'), contextIsolation: true, nodeIntegration: false } });
  await win.loadFile(path.join(root, 'dist/index.html'));
  const evaluate = code => win.webContents.executeJavaScript(code);
  await until(() => evaluate('Boolean(document.querySelector("textarea"))'));
  win.webContents.debugger.attach('1.3');
  const { root: document } = await win.webContents.debugger.sendCommand('DOM.getDocument');
  const { nodeId } = await win.webContents.debugger.sendCommand('DOM.querySelector', { nodeId: document.nodeId, selector: 'input[type=file]' });
  await win.webContents.debugger.sendCommand('DOM.setFileInputFiles', { nodeId, files: [fixture] });
  await until(() => evaluate('Boolean(document.querySelector(".attachment-chip"))'));
  const type = value => evaluate(`(() => { const el = document.querySelector('textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await type('Přečti testovací přílohu');
  await evaluate('document.querySelector(".send-button").click()');
  await until(() => Boolean(request));
  assert.deepEqual(request.filePaths, [fixture]);
  assert.equal(fs.readFileSync(request.filePaths[0], 'utf8'), 'PGEX-ATTACHMENT-7429');
  assert.equal(await evaluate('document.querySelector(".send-button").disabled'), true);
  await type('Rozepsaná další zpráva');
  finishRequest({ ok: true, currentChatId: request.chatId, messages: [
    { id: 'u1', role: 'user', content: request.text },
    { id: 'a1', role: 'assistant', content: '## Výsledek\n\n- Příloha načtena\n\n```txt\nPGEX-ATTACHMENT-7429\n```' },
  ] });
  await until(() => evaluate('Boolean(document.querySelector(".message-code")) && !document.querySelector(".send-button").disabled'));
  assert.equal(await evaluate('document.querySelector("textarea").value'), 'Rozepsaná další zpráva');
  assert.equal(await evaluate('document.querySelector(".message-code code").textContent.trim()'), 'PGEX-ATTACHMENT-7429');
  console.log('PASS: real Electron File -> preload -> IPC attachment path; pending input preserved; production Markdown rendered. Backend mocked.');
  clearTimeout(deadline);
  win.destroy();
  app.exit(0);
}).catch(async error => {
  console.error(error.message);
  if (win && !win.isDestroyed()) console.error(await win.webContents.executeJavaScript('document.body.innerText'));
  clearTimeout(deadline);
  if (win && !win.isDestroyed()) win.destroy();
  app.exit(1);
});
