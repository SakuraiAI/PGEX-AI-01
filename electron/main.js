import { app, BrowserWindow, ipcMain, Menu, nativeImage, screen, shell, Tray } from 'electron';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import os from 'node:os';
import fs from 'node:fs/promises';

import { readRuntimeSettings, writeRuntimeSettings } from './services/runtimeSettings.js';
import { buildUpdateFeed, openUpdateDownload, prepareUpdateDownload, restartAndInstallUpdate } from './services/updates.js';
import { getApplicationsState, launchApplication, updateApplicationPath } from './services/applications.js';
import { runLunaBridge } from './services/lunaBridge.js';
import { createSystemMetricsReader } from './services/systemMetrics.js';
import { registerActionIpc } from './ipc/actionIpc.js';
import { registerAgentIpc } from './ipc/agentIpc.js';


const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Preserve existing chat storage and settings across the product rename.
app.setPath('userData', path.join(app.getPath('appData'), 'lunaai-electron-shell'));
app.setName('PGEX');
const rendererDevServerUrl = process.env.LUNA_ELECTRON_RENDERER_URL || 'http://127.0.0.1:5173';
const useRendererDevServer = process.env.npm_lifecycle_event === 'dev'
  || process.env.LUNA_ELECTRON_USE_DEV_SERVER === '1';

let mainWindow = null;
let assistantWindow = null;
let tray = null;
let pendingLunaAction = null;
const readSystemMetrics = createSystemMetricsReader();


function mergePendingLunaAction(result) {
  if (!result || typeof result !== 'object') return result;
  if (pendingLunaAction) {
    return {
      ...result,
      pendingAction: {
        active: true,
        title: pendingLunaAction.title || 'Luna ceka na potvrzeni akce.',
      },
    };
  }
  return {
    ...result,
    pendingAction: {
      active: false,
      title: '',
      ...(result.pendingAction || {}),
    },
  };
}

async function runLunaChatAction(payload) {
  const result = await runLunaBridge(payload);
  const pendingTitle = String(result?.pendingAction?.title || '').trim();
  if (result?.ok && result?.pendingAction?.active) {
    pendingLunaAction = {
      payload,
      title: pendingTitle || String(result?.response || '').trim() || 'Luna ceka na potvrzeni akce.',
    };
  } else if (!result?.pendingAction?.active) {
    pendingLunaAction = null;
  }
  return mergePendingLunaAction(result);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 960,
    minWidth: 1240,
    minHeight: 760,
    show: false,
    frame: false,
    titleBarStyle: 'hidden',
    backgroundColor: '#060606',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show();
  });

  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    console.error('Electron renderer failed to load', {
      errorCode,
      errorDescription,
      validatedURL,
      useRendererDevServer,
    });
  });

  const builtIndexPath = path.join(app.getAppPath(), 'dist', 'index.html');
  if (useRendererDevServer) {
    mainWindow.loadURL(rendererDevServerUrl);
  } else {
    mainWindow.loadFile(builtIndexPath);
  }
}

function buildAssistantOverlayHtml() {
  return `<!doctype html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    * { box-sizing: border-box; }
    html, body {
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
      background: transparent;
      font-family: "Segoe UI", sans-serif;
      color: #f5f5f5;
    }
    .assistant-widget {
      width: 100%;
      height: 100%;
      display: grid;
      place-items: center;
      -webkit-app-region: drag;
      user-select: none;
    }
    .assistant-card {
      width: 248px;
      min-height: 248px;
      padding: 20px 18px 18px;
      display: grid;
      place-items: center;
      gap: 12px;
      border-radius: 34px;
      background:
        radial-gradient(circle at 50% 32%, rgba(255,255,255,0.12), transparent 44%),
        linear-gradient(180deg, rgba(18,18,18,0.9), rgba(5,5,5,0.82));
      border: 1px solid rgba(255,255,255,0.12);
      box-shadow: 0 28px 80px rgba(0,0,0,0.44), inset 0 1px 0 rgba(255,255,255,0.08);
      backdrop-filter: blur(20px);
    }
    .agents {
      width: 100%;
      display: flex;
      justify-content: space-between;
      color: rgba(255,255,255,0.72);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .orb {
      position: relative;
      width: 112px;
      height: 112px;
      display: grid;
      place-items: center;
      border-radius: 50%;
      background: rgba(15,15,15,0.92);
      border: 1px solid rgba(255,255,255,0.12);
      box-shadow: 0 0 46px rgba(150,210,255,0.12);
    }
    .orb::before,
    .orb::after {
      content: "";
      position: absolute;
      border-radius: inherit;
      border: 1px solid rgba(255,255,255,0.08);
      animation: ring 2.4s ease-in-out infinite;
    }
    .orb::before { inset: -14px; }
    .orb::after { inset: -28px; animation-delay: 0.35s; opacity: 0.58; }
    .core {
      width: 72px;
      height: 72px;
      border-radius: 50%;
      background: radial-gradient(circle at 35% 30%, #fff 0%, #e7e7e7 18%, #9c9c9c 52%, #111 100%);
      box-shadow: 0 0 42px rgba(255,255,255,0.28), 0 0 70px rgba(140,205,255,0.16);
      animation: pulse 1.35s ease-in-out infinite;
    }
    .status {
      text-align: center;
      display: grid;
      gap: 5px;
    }
    .status strong {
      font-size: 18px;
      letter-spacing: -0.03em;
    }
    .status span {
      color: rgba(255,255,255,0.58);
      font-size: 12px;
    }
    .actions {
      display: flex;
      gap: 8px;
      -webkit-app-region: no-drag;
    }
    button {
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 999px;
      padding: 8px 12px;
      background: rgba(255,255,255,0.08);
      color: #fff;
      font: inherit;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
    }
    button.primary {
      background: #f5f5f5;
      color: #111;
    }
    @keyframes pulse {
      0%, 100% { transform: scale(1); filter: brightness(1); }
      50% { transform: scale(1.12); filter: brightness(1.2); }
    }
    @keyframes ring {
      0%, 100% { transform: scale(0.96); opacity: 0.5; }
      50% { transform: scale(1.08); opacity: 1; }
    }
  </style>
</head>
<body>
  <main class="assistant-widget">
    <section class="assistant-card">
      <div class="agents"><span>LunaAI</span><span>XenoAI</span></div>
      <div class="orb"><div class="core"></div></div>
      <div class="status">
        <strong>Assistant mode</strong>
        <span>voice + vision + agent</span>
      </div>
      <div class="actions">
        <button class="primary" onclick="window.lunaDesktop?.window?.show?.()">Open</button>
        <button onclick="window.lunaDesktop?.window?.hideAssistantOverlay?.()">Hide</button>
      </div>
    </section>
  </main>
</body>
</html>`;
}

function positionAssistantWindow() {
  if (!assistantWindow) return;
  const primaryDisplay = screen.getPrimaryDisplay();
  const area = primaryDisplay.workArea;
  const bounds = assistantWindow.getBounds();
  assistantWindow.setPosition(
    Math.round(area.x + (area.width - bounds.width) / 2),
    Math.round(area.y + 28),
    false,
  );
}

function createAssistantWindow() {
  if (assistantWindow && !assistantWindow.isDestroyed()) return assistantWindow;
  assistantWindow = new BrowserWindow({
    width: 320,
    height: 320,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  assistantWindow.setAlwaysOnTop(true, 'screen-saver');
  assistantWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  assistantWindow.on('closed', () => {
    assistantWindow = null;
  });
  assistantWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(buildAssistantOverlayHtml())}`);
  return assistantWindow;
}

function showAssistantOverlay() {
  const overlay = createAssistantWindow();
  positionAssistantWindow();
  overlay.showInactive();
  return overlay;
}

function hideAssistantOverlay() {
  if (assistantWindow && !assistantWindow.isDestroyed()) {
    assistantWindow.hide();
  }
}

function showMainWindow() {
  if (!mainWindow) {
    createWindow();
    return;
  }
  mainWindow.show();
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.focus();
}

function createTray() {
  if (tray) return tray;
  const icon = nativeImage.createFromDataURL(
    'data:image/svg+xml;utf8,'
      + encodeURIComponent(`
        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
          <rect width="32" height="32" rx="10" fill="#0b0b0b"/>
          <circle cx="16" cy="16" r="10" fill="#d9d9d9"/>
          <circle cx="12" cy="12" r="4" fill="#ffffff"/>
          <circle cx="16" cy="16" r="14" fill="none" stroke="#5f6f7a" stroke-opacity=".55"/>
        </svg>
      `),
  );
  tray = new Tray(icon);
  tray.setToolTip('PGEX');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Zobrazit PGEX', click: showMainWindow },
    {
      label: 'Skrýt PGEX',
      click: () => {
        mainWindow?.hide();
      },
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        app.quit();
      },
    },
  ]));
  tray.on('click', showMainWindow);
  return tray;
}

app.whenReady().then(() => {
  registerActionIpc({
    ipcMain,
    getMainWindow: () => mainWindow,
  });
  registerAgentIpc({ ipcMain });

  createWindow();
  createTray();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

ipcMain.handle('window:minimize', () => {
  mainWindow?.minimize();
});

ipcMain.handle('window:maximize', () => {
  if (!mainWindow) return { maximized: false };
  if (mainWindow.isMaximized()) {
    mainWindow.unmaximize();
  } else {
    mainWindow.maximize();
  }
  return { maximized: mainWindow.isMaximized() };
});

ipcMain.handle('window:close', () => {
  mainWindow?.close();
});

ipcMain.handle('window:hide-to-tray', () => {
  createTray();
  mainWindow?.hide();
  return { ok: true, message: 'LunaAI is still running in the tray.' };
});

ipcMain.handle('window:show', () => {
  showMainWindow();
  return { ok: true };
});

ipcMain.handle('window:show-assistant-overlay', () => {
  showAssistantOverlay();
  return { ok: true, message: 'Assistant overlay is visible on the desktop.' };
});

ipcMain.handle('window:hide-assistant-overlay', () => {
  hideAssistantOverlay();
  return { ok: true, message: 'Assistant overlay hidden.' };
});

ipcMain.handle('app:get-meta', () => {
  const metrics = readSystemMetrics();
  return {
    appName: 'PGEX',
    version: app.getVersion(),
    platform: process.platform,
    deviceName: os.hostname(),
    os: `${os.type()} ${os.release()}`,
    arch: os.arch(),
    cpu: os.cpus()[0]?.model ?? 'Unknown CPU',
    gpu: metrics.gpu,
    gpuVendor: metrics.gpuVendor,
    cpuUsagePercent: metrics.cpuUsagePercent,
    gpuUsagePercent: metrics.gpuUsagePercent,
    memoryGb: Math.round(os.totalmem() / 1024 / 1024 / 1024),
    memoryUsedGb: metrics.memoryUsedGb,
    memoryUsagePercent: metrics.memoryUsagePercent,
    runtimeSettings: readRuntimeSettings(),
  };
});

ipcMain.handle('files:read-as-data-url', async (_, filePath) => {
  const targetPath = String(filePath || '').trim();
  if (!targetPath) {
    return { ok: false, message: 'Missing file path.' };
  }

  try {
    const fileBuffer = await fs.readFile(targetPath);
    const extension = path.extname(targetPath).toLowerCase();
    const mimeByExtension = {
      '.png': 'image/png',
      '.jpg': 'image/jpeg',
      '.jpeg': 'image/jpeg',
      '.webp': 'image/webp',
      '.gif': 'image/gif',
      '.wav': 'audio/wav',
      '.mp3': 'audio/mpeg',
      '.ogg': 'audio/ogg',
      '.opus': 'audio/ogg',
    };
    const mime = mimeByExtension[extension] || 'application/octet-stream';
    return {
      ok: true,
      dataUrl: `data:${mime};base64,${fileBuffer.toString('base64')}`,
    };
  } catch (error) {
    return {
      ok: false,
      message: String(error),
    };
  }
});

ipcMain.handle('files:write-temp-data-url', async (_, payload) => {
  const dataUrl = String(payload?.dataUrl || '').trim();
  const extension = String(payload?.extension || 'png').trim().replace(/^\.+/, '').toLowerCase() || 'png';
  const previousPath = String(payload?.previousPath || '').trim();
  const tempRoot = path.join(app.getPath('userData'), 'stream-captures');

  if (!dataUrl.startsWith('data:')) {
    return { ok: false, message: 'Invalid data URL payload.' };
  }

  try {
    await fs.mkdir(tempRoot, { recursive: true });

    const [header, encoded] = dataUrl.split(',', 2);
    if (!header || !encoded) {
      return { ok: false, message: 'Malformed data URL.' };
    }

    const nextPath = path.join(tempRoot, `stream_${Date.now()}.${extension}`);
    const buffer = Buffer.from(encoded, 'base64');
    await fs.writeFile(nextPath, buffer);

    if (previousPath) {
      const normalizedPrevious = path.resolve(previousPath);
      if (normalizedPrevious.startsWith(path.resolve(tempRoot))) {
        await fs.unlink(normalizedPrevious).catch(() => {});
      }
    }

    return { ok: true, path: nextPath };
  } catch (error) {
    return { ok: false, message: String(error) };
  }
});

ipcMain.handle('shell:open-external', async (_, rawUrl) => {
  const url = String(rawUrl || '').trim();
  if (!/^https?:\/\//i.test(url)) {
    return { ok: false, message: 'Only http and https links can be opened.' };
  }

  try {
    await shell.openExternal(url);
    return { ok: true };
  } catch (error) {
    return { ok: false, message: String(error) };
  }
});

ipcMain.handle('settings:get-runtime', () => {
  return readRuntimeSettings();
});

ipcMain.handle('settings:save-runtime', (_, nextSettings) => {
  return writeRuntimeSettings(nextSettings || {});
});

ipcMain.handle('apps:list', () => {
  return getApplicationsState();
});

ipcMain.handle('apps:update-path', (_, appKey, nextPath) => {
  return updateApplicationPath(String(appKey || ''), String(nextPath || ''));
});

ipcMain.handle('apps:launch', (_, appKey) => {
  return launchApplication(String(appKey || ''));
});

ipcMain.handle('updates:get-feed', () => {
  return buildUpdateFeed();
});

ipcMain.handle('updates:check', () => {
  return buildUpdateFeed();
});

ipcMain.handle('updates:download', (_, downloadUrl) => {
  const feed = buildUpdateFeed();
  return openUpdateDownload(String(downloadUrl || feed.downloadUrl || ''));
});

ipcMain.handle('updates:prepare', () => {
  return prepareUpdateDownload();
});

ipcMain.handle('updates:restart-and-install', () => {
  return restartAndInstallUpdate();
});

ipcMain.handle('luna:get-state', async () => {
  return mergePendingLunaAction(await runLunaBridge({ action: 'state' }));
});

ipcMain.handle('luna:create-chat', async (_, title) => {
  pendingLunaAction = null;
  return mergePendingLunaAction(await runLunaBridge({ action: 'create_chat', title: String(title || 'New chat') }));
});

ipcMain.handle('luna:switch-chat', async (_, chatId) => {
  return mergePendingLunaAction(await runLunaBridge({ action: 'switch_chat', chatId: String(chatId || '') }));
});

ipcMain.handle('luna:rename-chat', async (_, chatId, title) => {
  return mergePendingLunaAction(await runLunaBridge({ action: 'rename_chat', chatId: String(chatId || ''), title: String(title || '') }));
});

ipcMain.handle('luna:delete-chat', async (_, chatId) => {
  pendingLunaAction = null;
  return mergePendingLunaAction(await runLunaBridge({ action: 'delete_chat', chatId: String(chatId || '') }));
});

ipcMain.handle('luna:send-message', async (_, payload) => {
  return await runLunaChatAction({ action: 'send_message', ...(payload || {}) });
});

ipcMain.handle('luna:observe-desktop', async (_, payload) => {
  return mergePendingLunaAction(await runLunaBridge({ action: 'observe_desktop', ...(payload || {}) }));
});

ipcMain.handle('luna:analyze-visual', async (_, payload) => {
  return mergePendingLunaAction(await runLunaBridge({ action: 'analyze_visual', ...(payload || {}) }));
});

ipcMain.handle('luna:observe-system', async (_, payload) => {
  return mergePendingLunaAction(await runLunaBridge({ action: 'observe_system', ...(payload || {}) }));
});

ipcMain.handle('luna:transcribe-audio', async (_, payload) => {
  return mergePendingLunaAction(await runLunaBridge({ action: 'transcribe_audio', ...(payload || {}) }));
});

ipcMain.handle('luna:synthesize-speech', async (_, payload) => {
  return mergePendingLunaAction(await runLunaBridge({ action: 'synthesize_speech', ...(payload || {}) }));
});

ipcMain.handle('luna:set-observe-mode', async (_, enabled) => {
  return mergePendingLunaAction(await runLunaBridge({ action: 'set_observe_mode', enabled: Boolean(enabled) }));
});

ipcMain.handle('luna:confirm-pending-action', async () => {
  if (!pendingLunaAction?.payload) {
    return mergePendingLunaAction(await runLunaBridge({ action: 'state' }));
  }
  const replayPayload = { ...pendingLunaAction.payload, forceActionExecution: true };
  pendingLunaAction = null;
  return await runLunaChatAction({ action: 'send_message', ...replayPayload });
});

ipcMain.handle('luna:cancel-pending-action', async () => {
  pendingLunaAction = null;
  return mergePendingLunaAction(await runLunaBridge({ action: 'state' }));
});

ipcMain.handle('luna:future-action', async (_, payload) => {
  return {
    ok: true,
    message: 'IPC bridge is ready for Luna backend integration.',
    payload,
  };
});
