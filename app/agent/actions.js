import { registeredApplications } from './appDiscovery.js';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';

import { sanitizeCommandPayload, sanitizeText } from './security.js';

function buildResult(success, action, target, message, error = null, extra = {}) {
  return {
    success,
    action,
    target,
    message,
    error,
    ...extra,
  };
}

function normalizeUrl(value) {
  const raw = sanitizeText(value);
  if (!raw) return '';
  if (/^localhost:/i.test(raw)) return `http://${raw}`;
  if (/^www\./i.test(raw)) return `https://${raw}`;
  if (!/^https?:\/\//i.test(raw)) return `https://${raw}`;
  return raw;
}

function appCommandCandidates(target) {
  const candidates = {
    vscode: ['code.cmd', 'code.exe', 'code'],
    chrome: ['chrome.exe', 'chrome'],
    blender: ['blender.exe', 'blender'],
    unreal: ['UnrealEditor.exe', 'UnrealEditor', 'UE4Editor.exe', 'UE4Editor'],
    discord: ['Discord.exe', 'Discord'],
    explorer: ['explorer.exe', 'explorer'],
  };
  return candidates[target] || [target, `${target}.exe`];
}

function findExecutableOnPath(target) {
  const lookupCommand = process.platform === 'win32' ? 'where' : 'which';
  for (const candidate of appCommandCandidates(target)) {
    const result = spawnSync(lookupCommand, [candidate], {
      encoding: 'utf8',
      windowsHide: true,
      shell: false,
    });
    if (result.status === 0) {
      const first = String(result.stdout || '').split(/\r?\n/).find(Boolean);
      if (first) return first.trim();
    }
  }
  return '';
}

function resolveAppPath(target, context) {
  const configured = sanitizeText(context.appPaths[target]);
  if (configured) return configured;
  return findExecutableOnPath(target);
}

async function openApp(command, context) {
  const target = sanitizeText(command?.target || '').toLowerCase();
  const registered = await registeredApplications('resolve', target);
  if (registered.ok && registered.app) {
    const result = await registeredApplications('launch', registered.app.key);
    return buildResult(Boolean(result.ok), 'open_app', target, result.message, result.ok ? null : 'APP_LAUNCH_FAILED');
  }
  const appPath = resolveAppPath(target, context);
  if (!appPath) {
    return buildResult(false, 'open_app', target, `App '${target}' is not configured and was not found on PATH.`, 'APP_NOT_FOUND');
  }

  try {
    const child = spawn(appPath, [], {
      cwd: context.workspaceRoot,
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      shell: false,
    });
    child.unref();
    return buildResult(true, 'open_app', target, `${target} opened successfully`, null, { pid: child.pid ?? null });
  } catch (error) {
    return buildResult(false, 'open_app', target, `Failed to open ${target}`, String(error));
  }
}

async function openUrl(command, context) {
  const url = normalizeUrl(command?.target || command?.url || '');
  if (!url) {
    return buildResult(false, 'open_url', '', 'URL is missing.', 'MISSING_URL');
  }

  const chromePath = resolveAppPath('chrome', context);
  const executable = chromePath || (process.platform === 'win32' ? 'cmd' : 'xdg-open');
  const args = chromePath ? [url] : process.platform === 'win32' ? ['/c', 'start', '', url] : [url];
  try {
    const child = spawn(executable, args, {
      cwd: context.workspaceRoot,
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      shell: false,
    });
    child.unref();
    return buildResult(true, 'open_url', url, `URL opened: ${url}`, null, { pid: child.pid ?? null });
  } catch (error) {
    return buildResult(false, 'open_url', url, 'Failed to open URL', String(error));
  }
}

async function findAppPathAction(command, context) {
  const target = sanitizeText(command?.target || '').toLowerCase();
  const appPath = resolveAppPath(target, context);
  if (!appPath) {
    return buildResult(false, 'find_app_path', target, `App '${target}' was not found.`, 'APP_NOT_FOUND');
  }
  return buildResult(true, 'find_app_path', target, `Resolved ${target}: ${appPath}`, null, { appPath });
}

async function runCommand(command, context) {
  const { executable, args, cwd } = sanitizeCommandPayload(command);
  const target = executable;
  const workingDirectory = cwd || context.workspaceRoot;
  const joined = [executable, ...args].join(' ').toLowerCase();

  if (executable === 'dir') {
    return await listFilesAction({ action: 'list_files', target: workingDirectory }, context);
  }
  if (executable === 'echo') {
    return buildResult(true, 'run_command', 'echo', args.join(' '), null, { stdout: args.join(' ') });
  }
  if (joined === 'npm start' || joined === 'npm run dev' || joined === 'npm run start') {
    try {
      const child = spawn(executable, args, {
        cwd: workingDirectory,
        detached: true,
        stdio: 'ignore',
        windowsHide: false,
        shell: false,
        env: {
          ...process.env,
          PYTHONUTF8: '1',
          PYTHONIOENCODING: 'utf-8',
        },
      });
      child.unref();
      return buildResult(true, 'run_command', target, `Started ${joined}`, null, { pid: child.pid ?? null, inProgress: true });
    } catch (error) {
      return buildResult(false, 'run_command', target, 'Command failed to start', String(error));
    }
  }

  return await new Promise((resolve) => {
    const child = spawn(executable, args, {
      cwd: workingDirectory,
      shell: false,
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
      },
    });

    let stdout = '';
    let stderr = '';

    child.stdout?.setEncoding('utf8');
    child.stderr?.setEncoding('utf8');

    child.stdout?.on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr?.on('data', (chunk) => {
      stderr += chunk;
    });

    child.on('error', (error) => {
      resolve(buildResult(false, 'run_command', target, 'Command failed to start', String(error)));
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve(buildResult(true, 'run_command', target, 'Command completed successfully', null, {
          code,
          stdout: stdout.trim(),
          stderr: stderr.trim(),
        }));
        return;
      }
      resolve(buildResult(false, 'run_command', target, 'Command exited with an error', stderr.trim() || `Exit code ${code}`, {
        code,
        stdout: stdout.trim(),
        stderr: stderr.trim(),
      }));
    });
  });
}

async function readFileAction(command, context) {
  const target = path.resolve(sanitizeText(command?.target || command?.path || ''));
  try {
    const content = await fs.readFile(target, 'utf8');
    return buildResult(true, 'read_file', target, 'File read successfully', null, { content });
  } catch (error) {
    return buildResult(false, 'read_file', target, 'Failed to read file', String(error));
  }
}

async function writeFileAction(command, context) {
  const target = path.resolve(sanitizeText(command?.target || command?.path || ''));
  const content = typeof command?.content === 'string' ? command.content : '';
  try {
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.writeFile(target, content, 'utf8');
    return buildResult(true, 'write_file', target, 'File written successfully');
  } catch (error) {
    return buildResult(false, 'write_file', target, 'Failed to write file', String(error));
  }
}

async function listFilesAction(command, context) {
  const target = path.resolve(sanitizeText(command?.target || command?.path || context.workspaceRoot));
  try {
    const entries = await fs.readdir(target, { withFileTypes: true });
    return buildResult(true, 'list_files', target, 'Files listed successfully', null, {
      entries: entries.map((entry) => ({
        name: entry.name,
        type: entry.isDirectory() ? 'directory' : entry.isFile() ? 'file' : 'other',
      })),
    });
  } catch (error) {
    return buildResult(false, 'list_files', target, 'Failed to list files', String(error));
  }
}

async function getSystemInfoAction() {
  return buildResult(true, 'get_system_info', 'local_pc', 'System info retrieved successfully', null, {
    system: {
      platform: process.platform,
      release: os.release(),
      arch: os.arch(),
      hostname: os.hostname(),
      cpuModel: os.cpus()[0]?.model || 'Unknown CPU',
      cpuCount: os.cpus().length,
      totalMemoryGb: Math.round(os.totalmem() / 1024 / 1024 / 1024),
      freeMemoryGb: Math.round(os.freemem() / 1024 / 1024 / 1024),
    },
  });
}

export function createAgentActions() {
  return {
    open_app: openApp,
    open_url: openUrl,
    run_command: runCommand,
    read_file: readFileAction,
    write_file: writeFileAction,
    list_files: listFilesAction,
    find_app_path: findAppPathAction,
    get_system_info: getSystemInfoAction,
  };
}
