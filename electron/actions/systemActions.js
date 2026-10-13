import { shell } from 'electron';
import { launchApplication } from '../services/applications.js';

function normalizeTarget(value) {
  return String(value || '').trim().toLowerCase();
}

function normalizeUrl(value) {
  const target = String(value || '').trim();
  if (!target) return '';
  if (/^localhost:/i.test(target)) return `http://${target}`;
  if (/^www\./i.test(target)) return `https://${target}`;
  if (/^https?:\/\//i.test(target)) return target;
  return '';
}

export function createSystemActions() {
  return {
    async execute(action) {
      const type = String(action?.type || '').trim();
      const target = String(action?.target || '').trim();

      if (type === 'open_app') {
        const result = await launchApplication(normalizeTarget(target));
        return {
          ok: Boolean(result?.ok),
          executed: Boolean(result?.ok),
          status: result?.ok ? 'executed' : 'failed',
          message: result?.message || `Application could not be launched: ${target}`,
          action,
        };
      }

      if (type === 'open_url') {
        const url = normalizeUrl(target || action?.args?.url);
        if (!url) {
          return {
            ok: false,
            executed: false,
            status: 'blocked',
            message: 'Only http, https, localhost, and www URLs can be opened by the Action Engine.',
            action,
          };
        }

        await shell.openExternal(url);
        return {
          ok: true,
          executed: true,
          status: 'executed',
          message: `Opened URL: ${url}`,
          action,
        };
      }

      return {
        ok: false,
        executed: false,
        status: 'not_implemented',
        message: `System action is approved by policy but not implemented in Electron yet: ${type}. Use Luna backend action routing for this capability for now.`,
        action,
      };
    },
  };
}
