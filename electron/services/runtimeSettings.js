import { app } from 'electron';
import path from 'node:path';
import fs from 'node:fs';
import { getSharedBackendSettingsPath } from './backendSettings.js';

export const defaultRuntimeSettings = { profile: 'balanced', cpuLimit: 55, gpuLimit: 60, memoryLimit: 50 };
export function normalizeRuntimeSettings(value = {}) {
  const normalized = {};
  for (const key of ['cpuLimit', 'gpuLimit', 'memoryLimit']) {
    const number = Number(value[key] ?? defaultRuntimeSettings[key]);
    normalized[key] = Number.isFinite(number) ? Math.max(10, Math.min(100, Math.round(number))) : defaultRuntimeSettings[key];
  }
  const budget = Math.min(normalized.cpuLimit, normalized.gpuLimit, normalized.memoryLimit);
  normalized.profile = budget <= 35 ? 'light' : budget <= 50 ? 'balanced' : 'focused';
  return normalized;
}

export function readRuntimeSettings() {
  try {
    const backendPath = getSharedBackendSettingsPath();
    if (fs.existsSync(backendPath)) {
      const backend = JSON.parse(fs.readFileSync(backendPath, 'utf8'));
      return normalizeRuntimeSettings({ cpuLimit: backend.cpu_limit_percent, gpuLimit: backend.gpu_limit_percent, memoryLimit: backend.memory_limit_percent });
    }
    const legacyPath = path.join(app.getPath('userData'), 'runtime-settings.json');
    if (fs.existsSync(legacyPath)) return normalizeRuntimeSettings(JSON.parse(fs.readFileSync(legacyPath, 'utf8')));
  } catch { /* Defaults are used for an unreadable settings file; saving reports errors. */ }
  return { ...defaultRuntimeSettings };
}

export function writeRuntimeSettings(nextSettings) {
  const normalized = normalizeRuntimeSettings(nextSettings);
  const backendPath = getSharedBackendSettingsPath();
  // The file actually read by the model is the source of truth. Never report
  // success if it could not be written, and preserve all unrelated preferences.
  const payload = fs.existsSync(backendPath) ? JSON.parse(fs.readFileSync(backendPath, 'utf8')) : {};
  payload.cpu_limit_percent = normalized.cpuLimit;
  payload.gpu_limit_percent = normalized.gpuLimit;
  payload.memory_limit_percent = normalized.memoryLimit;
  fs.mkdirSync(path.dirname(backendPath), { recursive: true });
  fs.writeFileSync(backendPath, JSON.stringify(payload, null, 2), 'utf8');
  return normalized;
}
