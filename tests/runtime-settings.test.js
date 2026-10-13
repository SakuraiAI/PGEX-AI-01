// @vitest-environment node
import { beforeEach, afterEach, it, expect, vi } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const state = vi.hoisted(() => ({ root: '', file: '' }));
vi.mock('electron', () => ({ app: { getPath: () => state.root } }));
vi.mock('../electron/services/backendSettings.js', () => ({ getSharedBackendSettingsPath: () => state.file }));
import { readRuntimeSettings, writeRuntimeSettings, normalizeRuntimeSettings } from '../electron/services/runtimeSettings';
beforeEach(() => { state.root = fs.mkdtempSync(path.join(os.tmpdir(), 'pgex-settings-test-')); state.file = path.join(state.root, 'settings.json'); });
afterEach(() => { for (const name of fs.readdirSync(state.root)) { const file = path.join(state.root, name); if (fs.statSync(file).isFile()) fs.unlinkSync(file); } fs.rmdirSync(state.root); });

it('writes to the backend file used by the model and preserves unrelated settings', () => {
  fs.writeFileSync(state.file, JSON.stringify({ vscode_path: 'keep', allow_app_launch: true }));
  writeRuntimeSettings({ cpuLimit: 70, gpuLimit: 70, memoryLimit: 70 });
  expect(JSON.parse(fs.readFileSync(state.file, 'utf8'))).toEqual({ vscode_path: 'keep', allow_app_launch: true, cpu_limit_percent: 70, gpu_limit_percent: 70, memory_limit_percent: 70 });
  expect(readRuntimeSettings().profile).toBe('focused');
});
it('reads authoritative backend settings instead of a stale desktop copy', () => {
  fs.writeFileSync(path.join(state.root, 'runtime-settings.json'), JSON.stringify({ cpuLimit: 35, gpuLimit: 35, memoryLimit: 35 }));
  fs.writeFileSync(state.file, JSON.stringify({ cpu_limit_percent: 70, gpu_limit_percent: 70, memory_limit_percent: 70 }));
  expect(readRuntimeSettings().memoryLimit).toBe(70);
});
it('does not silently succeed when backend preferences cannot be read or saved', () => {
  fs.writeFileSync(state.file, 'invalid json');
  expect(() => writeRuntimeSettings({ cpuLimit: 70 })).toThrow();
});
it('clamps invalid settings at the IPC boundary', () => {
  expect(normalizeRuntimeSettings({ cpuLimit: Infinity, gpuLimit: -1, memoryLimit: 200 })).toMatchObject({ cpuLimit: 55, gpuLimit: 10, memoryLimit: 100 });
});
