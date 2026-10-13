import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

import { getSharedBackendSettingsPath, readBackendUserSettings } from './backendSettings.js';


const applicationCatalog = [
  { id: 'app-vscode', key: 'vscode', name: 'VS Code', detail: 'Connected workspace editor', pathField: 'vscode_path' },
  { id: 'app-blender', key: 'blender', name: 'Blender', detail: '3D and asset creation layer', pathField: 'blender_path' },
  { id: 'app-unreal', key: 'unreal', name: 'Unreal Engine', detail: 'Real-time scene and game environment', pathField: 'unreal_engine_path' },
];

export function getApplicationsState() {
  const backend = readBackendUserSettings();
  return applicationCatalog.map((appDef) => {
    const configuredPath = String(backend[appDef.pathField] || '').trim();
    const pathExists = configuredPath ? fs.existsSync(configuredPath) : false;
    return {
      id: appDef.id,
      key: appDef.key,
      title: appDef.name,
      detail: appDef.detail,
      path: configuredPath,
      connected: pathExists,
      status: pathExists ? 'Connected' : configuredPath ? 'Path missing' : 'Not connected',
      ctaLabel: pathExists ? 'Open' : 'Setup required',
    };
  });
}

export function updateApplicationPath(appKey, nextPath) {
  const appDef = applicationCatalog.find((item) => item.key === appKey);
  if (!appDef) {
    return { ok: false, message: 'Application could not be found.' };
  }

  try {
    const backendPath = getSharedBackendSettingsPath();
    const payload = fs.existsSync(backendPath)
      ? JSON.parse(fs.readFileSync(backendPath, 'utf8'))
      : {};
    payload[appDef.pathField] = String(nextPath || '').trim();
    fs.mkdirSync(path.dirname(backendPath), { recursive: true });
    fs.writeFileSync(backendPath, JSON.stringify(payload, null, 2), 'utf8');
    const updated = getApplicationsState().find((item) => item.key === appKey);
    return {
      ok: true,
      message: `${appDef.name} path saved.`,
      app: updated,
      apps: getApplicationsState(),
    };
  } catch (error) {
    return { ok: false, message: `${appDef.name} path could not be saved. ${error}` };
  }
}

export function launchApplication(appKey) {
  const appState = getApplicationsState().find((item) => item.key === appKey);
  if (!appState) {
    return { ok: false, message: 'Application could not be found.' };
  }
  if (!appState.connected || !appState.path) {
    return { ok: false, message: `${appState.title} is not connected yet.` };
  }
  try {
    const child = spawn(appState.path, [], {
      detached: true,
      stdio: 'ignore',
      windowsHide: false,
    });
    child.unref();
    return { ok: true, message: `${appState.title} launched.`, app: appState };
  } catch (error) {
    return { ok: false, message: `${appState.title} failed to launch. ${error}` };
  }
}
