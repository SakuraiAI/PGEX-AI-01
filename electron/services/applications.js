import { registeredApplications } from '../../app/agent/appDiscovery.js';

let cached = null;
let pending = null;
let loadedAt = 0;

export async function getApplicationsState(refresh = false) {
  if (!refresh && cached && Date.now() - loadedAt < 60000) return cached;
  if (pending) return pending;
  pending = registeredApplications('list').then(result => {
    if (!result.ok) throw new Error(result.message);
    cached = result.apps || [];
    loadedAt = Date.now();
    return cached;
  }).finally(() => { pending = null; });
  return pending;
}

export async function launchApplication(appKey) {
  // The Python resolver validates the key/name against Windows on each launch.
  return registeredApplications('launch', appKey);
}
