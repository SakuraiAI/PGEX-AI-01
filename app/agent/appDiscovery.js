import { execFile } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const bundledPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
export function registeredApplications(command = 'list', query = '') {
  return new Promise((resolve) => {
    const python = process.env.LUNA_PYTHON || (fs.existsSync(bundledPython) ? bundledPython : 'python');
    execFile(python, [path.join(root, 'app/tools/app_discovery.py'), command, String(query)], {
      cwd: root, windowsHide: true, timeout: 20000, maxBuffer: 2 * 1024 * 1024,
      env: { ...process.env, PYTHONUTF8: '1' },
    }, (error, stdout) => {
      if (error) return resolve({ ok: false, message: 'Seznam aplikací Windows není dostupný. Zkus obnovit seznam.' });
      try { resolve(JSON.parse(stdout)); }
      catch { resolve({ ok: false, message: 'Windows nevrátil čitelný seznam aplikací.' }); }
    });
  });
}
