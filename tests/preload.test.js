// @vitest-environment node
import { it, expect, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

it('uses Electron webUtils to resolve a real File through the isolated preload', () => {
  let api;
  const file = { name: 'report.txt' };
  const getPathForFile = vi.fn(() => 'C:/fixtures/report.txt');
  runInNewContext(readFileSync(new URL('../electron/preload.cjs', import.meta.url), 'utf8'), {
    require: () => ({ contextBridge: { exposeInMainWorld: (name, value) => { api = value; } }, ipcRenderer: {}, webUtils: { getPathForFile } }),
  });
  expect(api.files.getPathForFile(file)).toBe('C:/fixtures/report.txt');
  expect(getPathForFile).toHaveBeenCalledWith(file);
});
