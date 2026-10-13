import { useEffect, useMemo, useRef, useState } from 'react';
import AppShell from './layouts/AppShell';
import TopBar from './components/TopBar';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import ChatInput from './components/ChatInput';
import ContextMenu from './components/ContextMenu';
import NotificationsPanel from './components/NotificationsPanel';
import ProjectModal from './components/ProjectModal';
import EyesPage from './pages/EyesPage';
import SectionPage from './pages/SectionPage';
import SettingsPage from './pages/SettingsPage';
import UpdatesPage from './pages/UpdatesPage';
import { normalizeTransportText } from './utils/textRepair';
import {
  initialChats,
  initialMessages,
  projectCards,
  updates,
} from './data/mockData';

const sectionTitles = {
  chat: { title: 'Luna Workspace', subtitle: 'A calm command surface for Luna, Xeno, the agent layer, and future local reasoning.' },
  vision: { title: 'Vision', subtitle: 'Recognize screenshots, documents, videos, and attached visual context.' },
  projects: { title: 'Projekty', subtitle: 'Rozpracované úkoly a konverzace na jednom místě.' },
  updates: { title: 'Updates', subtitle: 'Patch-note style system feed for LunaAI and internal layer changes.' },
  settings: { title: 'Settings', subtitle: 'Runtime, identity, and control surfaces prepared for a desktop AI system.' },
};

const fallbackMeta = {
  version: '0.1.0',
  deviceName: 'LunaAI Desktop',
  os: 'Windows',
  arch: 'x64',
  cpu: 'Unknown CPU',
  gpu: 'Unavailable',
  gpuVendor: 'unknown',
  cpuUsagePercent: null,
  gpuUsagePercent: null,
  memoryGb: 0,
  memoryUsedGb: 0,
  memoryUsagePercent: null,
  platform: 'desktop',
};

const STORAGE_KEYS = {
  chats: 'lunaai-react-chats',
  currentChatId: 'lunaai-react-current-chat-id',
  messages: 'lunaai-react-chat-messages',
  projects: 'lunaai-react-projects',
  settings: 'lunaai-react-settings',
  page: 'lunaai-react-page',
  seenUpdateVersion: 'lunaai-seen-update-version',
};

const defaultRuntimeSettings = {
  profile: 'balanced',
  cpuLimit: 55,
  gpuLimit: 60,
  memoryLimit: 50,
};

const baseNotifications = [];

function buildFallbackUpdateFeed(items, runtimeVersion = '0.1.0') {
  const first = items[0] || null;
  return {
    currentVersion: runtimeVersion || '0.1.0',
    latestVersion: first?.version || runtimeVersion || '0.1.0',
    publishedAt: first?.date || '',
    channel: 'stable',
    updateAvailable: false,
    downloadUrl: '',
    downloadStatus: 'none',
    readyToInstall: false,
    downloadedPath: '',
    autoDownloadSupported: false,
    entries: items,
  };
}

function readStoredJson(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function buildInitialChatThreads() {
  if (initialChats.length === 0 || initialMessages.length === 0) return {};
  const firstId = initialChats[0]?.id;
  return firstId ? { [firstId]: initialMessages } : {};
}



function toLocalFileUrl(filePath) {
  const normalized = String(filePath || '').trim().replace(/\\/g, '/');
  if (!normalized) return '';
  if (/^file:\/\//i.test(normalized)) return normalized;
  return encodeURI(`file:///${normalized.replace(/^\/+/, '')}`);
}

async function readLocalPreviewDataUrl(filePath) {
  const targetPath = String(filePath || '').trim();
  const api = window.lunaDesktop?.files;
  if (!targetPath || !api?.readAsDataUrl) return '';
  const result = await api.readAsDataUrl(targetPath).catch(() => null);
  return result?.ok && result?.dataUrl ? String(result.dataUrl) : '';
}

function mergeFloat32Chunks(chunks) {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(totalLength);
  let offset = 0;
  chunks.forEach((chunk) => {
    merged.set(chunk, offset);
    offset += chunk.length;
  });
  return merged;
}

function downsampleFloat32Buffer(buffer, inputSampleRate, outputSampleRate = 16000) {
  if (inputSampleRate === outputSampleRate) return buffer;
  const ratio = inputSampleRate / outputSampleRate;
  const nextLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(nextLength);
  let offsetResult = 0;
  let offsetBuffer = 0;

  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let sum = 0;
    let count = 0;
    for (let index = offsetBuffer; index < nextOffsetBuffer && index < buffer.length; index += 1) {
      sum += buffer[index];
      count += 1;
    }
    result[offsetResult] = count ? sum / count : 0;
    offsetResult += 1;
    offsetBuffer = nextOffsetBuffer;
  }

  return result;
}

function encodePcm16Wav(samples, sampleRate = 16000) {
  const bytesPerSample = 2;
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
  const view = new DataView(buffer);

  const writeString = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * bytesPerSample, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerSample, true);
  view.setUint16(32, bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, samples.length * bytesPerSample, true);

  let offset = 44;
  for (let index = 0; index < samples.length; index += 1, offset += 2) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }

  return new Blob([view], { type: 'audio/wav' });
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function shouldConsultXeno(text) {
  return /\b(navrhni|architektura|architekturu|rizika|tok dat|rozdelej|faze|f?ze|kroky|implementace|plan|pl[a?]n|workspace|strategi|system)\b/i.test(text);
}

function getRequestedSpeaker(text) {
  const normalized = String(text || '').trim().toLowerCase();
  if (!normalized) return null;
  if (/\bxeno(ai)?\b/.test(normalized)) return 'Xeno';
  if (/\bluna(ai)?\b/.test(normalized) || /\bluno\b/.test(normalized)) return 'Luna';
  return null;
}

function getLatestUserIntent(messageList) {
  const messages = Array.isArray(messageList) ? messageList : [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const candidate = messages[index];
    if (candidate?.role === 'user' && String(candidate?.content || '').trim()) {
      return String(candidate.content).trim();
    }
  }
  return '';
}

function buildActionKey(action) {
  if (!action?.type) return '';
  return JSON.stringify({
    type: action.type,
    target: action.target || '',
    args: action.args || {},
  });
}

function createThinkingState(text, { fallbackToLuna = true } = {}) {
  const requestedSpeaker = getRequestedSpeaker(text);
  const consultXeno = shouldConsultXeno(text);

  if (requestedSpeaker === 'Xeno') {
    return {
      visible: true,
      lunaActive: false,
      xenoActive: true,
      tracks: [
        {
          speaker: 'Xeno',
          title: 'Xeno direct',
          note: 'Prebira reasoning vrstvu a sklada odpoved.',
        },
      ],
    };
  }

  if (requestedSpeaker === 'Luna') {
    return {
      visible: true,
      lunaActive: true,
      xenoActive: consultXeno,
      tracks: consultXeno
        ? [
            {
              speaker: 'Luna',
              title: 'Luna',
              note: 'Drzi odpoved a posila Xeno strategic check.',
            },
            {
              speaker: 'Xeno',
              title: 'Xeno -> Luna',
              note: 'Kontroluje rizika, strukturu a dalsi nejlepsi krok.',
            },
          ]
        : [
            {
              speaker: 'Luna',
              title: 'Luna',
              note: 'Sklada primou odpoved bez Xeno handoffu.',
            },
          ],
    };
  }

  return {
    visible: true,
    lunaActive: fallbackToLuna,
    xenoActive: consultXeno,
    tracks: consultXeno
      ? [
          {
            speaker: 'Luna',
            title: 'Luna',
            note: 'Drzi hlavni odpoved a sklada uzivatelskou vrstvu.',
          },
          {
            speaker: 'Xeno',
            title: 'Xeno -> Luna',
            note: 'Pridava planning, rizika a strategic support.',
          },
        ]
      : fallbackToLuna
        ? [
            {
              speaker: 'Luna',
              title: 'Luna',
              note: 'Drzi primou odpoved bez druhe vrstvy.',
            },
          ]
        : [],
  };
}

const idleThinkingState = {
  visible: false,
  lunaActive: false,
  xenoActive: false,
  tracks: [],
};

function buildRendererFallbackMeta() {
  const ua = navigator.userAgent || '';
  const platform = navigator.userAgentData?.platform || navigator.platform || 'desktop';
  const memoryGb = Number(navigator.deviceMemory || 0);
  const cpuCores = Number(navigator.hardwareConcurrency || 0);

  let os = 'Desktop';
  if (/Windows/i.test(ua)) os = 'Windows';
  else if (/Mac/i.test(ua)) os = 'macOS';
  else if (/Linux/i.test(ua)) os = 'Linux';

  return {
    deviceName: 'This device',
    os,
    arch: /64/.test(ua) ? 'x64' : 'unknown',
    cpu: cpuCores ? `${cpuCores} logical cores` : 'CPU available',
    gpu: 'Renderer mode',
    gpuVendor: 'renderer',
    memoryGb,
    memoryUsedGb: memoryGb ? Math.max(1, Math.round(memoryGb * 0.5)) : 0,
    memoryUsagePercent: memoryGb ? 50 : null,
    platform: String(platform || 'desktop').toLowerCase(),
  };
}

export default function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(() => {
    const storedPage = window.localStorage.getItem(STORAGE_KEYS.page) || 'chat';
    if (['eyes', 'vision', 'friends'].includes(storedPage)) return 'chat';
    if (storedPage === 'gallery') return 'chat';
    if (storedPage === 'applications') return 'settings';
    return storedPage;
  });
  const [chats, setChats] = useState(() => readStoredJson(STORAGE_KEYS.chats, initialChats));
  const [selectedTrashIds, setSelectedTrashIds] = useState([]);
  const [trashBusy, setTrashBusy] = useState(false);
  const [trashedChatIds, setTrashedChatIds] = useState(() => readStoredJson('lunaai-trash-v1', []));
  useEffect(() => { window.localStorage.setItem('lunaai-trash-v1', JSON.stringify(trashedChatIds)); }, [trashedChatIds]);
  const [currentChatId, setCurrentChatId] = useState(() => window.localStorage.getItem(STORAGE_KEYS.currentChatId) || initialChats[0]?.id || '');
  const [chatMessages, setChatMessages] = useState(() => readStoredJson(STORAGE_KEYS.messages, buildInitialChatThreads()));
  const [projects, setProjects] = useState(() => readStoredJson(STORAGE_KEYS.projects, projectCards));
  const [runtimeSettings, setRuntimeSettings] = useState(() => readStoredJson(STORAGE_KEYS.settings, defaultRuntimeSettings));
  const [applicationsState, setApplicationsState] = useState([]);
  const [selectedApplicationId, setSelectedApplicationId] = useState('');
  const [composer, setComposer] = useState('');
  const [attachment, setAttachment] = useState(null);
  const [observeModeEnabled, setObserveModeEnabled] = useState(false);
  const [pendingDesktopContext, setPendingDesktopContext] = useState(null);
  const [desktopObservation, setDesktopObservation] = useState(null);
  const [desktopPreviewUrl, setDesktopPreviewUrl] = useState('');
  const [status, setStatus] = useState('LunaAI desktop shell ready.');
  const [contextMenu, setContextMenu] = useState({ visible: false, x: 0, y: 0, kind: 'chat', targetId: '', title: '', saved: false });
  const [appMeta, setAppMeta] = useState(fallbackMeta);
  const [seenUpdateVersion, setSeenUpdateVersion] = useState(() => window.localStorage.getItem(STORAGE_KEYS.seenUpdateVersion) || '');
  const [updateFeed, setUpdateFeed] = useState(() => buildFallbackUpdateFeed(updates, fallbackMeta.version));
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [projectType, setProjectType] = useState('investing');
  const [chatBusy, setChatBusy] = useState(false);
  const sendLockRef = useRef(false);
  const [chatError, setChatError] = useState(null);
  const [sendingMessage, setSendingMessage] = useState(null);
  const [eyesBusy, setEyesBusy] = useState(false);
  const [thinkingState, setThinkingState] = useState(idleThinkingState);
  const [pendingAction, setPendingAction] = useState({ active: false, title: '' });
  const [actionEnginePending, setActionEnginePending] = useState({ active: false, title: '' });
  const messages = currentChatId ? chatMessages[currentChatId] || [] : [];
  const announcedUpdateVersionRef = useRef('');

  const notifications = useMemo(() => {
    const items = [...baseNotifications];
    const updateReady = Boolean(updateFeed?.readyToInstall);
    if (updateFeed?.updateAvailable && updateFeed.latestVersion && (updateReady || updateFeed.latestVersion !== seenUpdateVersion)) {
      items.unshift({
        id: `update-${updateFeed.latestVersion}`,
        kind: 'update',
        label: 'Update',
        title: updateReady ? `Nov\u00e1 verze ${updateFeed.latestVersion} je p\u0159ipraven\u00e1` : `Nov\u00fd update ${updateFeed.latestVersion}`,
        detail: updateReady
          ? 'Update je sta\u017een\u00fd. Kliknut\u00edm otev\u0159e\u0161 Restart & Update.'
          : updateFeed.downloadStatus === 'missing-url'
            ? 'Update je dostupn\u00fd, ale release manifest zat\u00edm nem\u00e1 downloadUrl.'
            : 'LunaAI p\u0159ipravuje update na pozad\u00ed.',
        version: updateFeed.latestVersion,
      });
    }
    return items;
  }, [seenUpdateVersion, updateFeed]);
  const notificationCount = notifications.length;
  const pageData = sectionTitles[page] || sectionTitles.chat;

  useEffect(() => () => {
    if (attachment?.previewUrl?.startsWith('blob:')) {
      URL.revokeObjectURL(attachment.previewUrl);
    }
  }, [attachment]);



  useEffect(() => {
    const screenshotPath = String(desktopObservation?.screenshot_path || '').trim();
    const api = window.lunaDesktop?.files;

    if (!screenshotPath || !api?.readAsDataUrl) {
      setDesktopPreviewUrl('');
      return undefined;
    }

    let cancelled = false;

    async function loadPreview() {
      const result = await api.readAsDataUrl(screenshotPath).catch(() => null);
      if (cancelled) return;
      if (result?.ok && result?.dataUrl) {
        setDesktopPreviewUrl(String(result.dataUrl));
      } else {
        setDesktopPreviewUrl('');
      }
    }

    loadPreview();

    return () => {
      cancelled = true;
    };
  }, [desktopObservation?.screenshot_path]);

  useEffect(() => {
    const api = window.lunaDesktop;

    async function refreshMeta() {
      if (!api?.app?.getMeta) {
        setAppMeta((current) => ({ ...current, ...buildRendererFallbackMeta() }));
        return;
      }

      try {
        const meta = await api.app.getMeta();
        setAppMeta((current) => ({ ...current, ...meta }));
        if (meta?.runtimeSettings) {
          setRuntimeSettings((current) => ({ ...current, ...meta.runtimeSettings }));
        }
      } catch {
        setAppMeta((current) => ({ ...current, ...buildRendererFallbackMeta() }));
      }
    }

    async function refreshApplications() {
      if (!api?.apps?.list) {
        return;
      }
      try {
        const nextApps = await api.apps.list();
        setApplicationsState(Array.isArray(nextApps) ? nextApps : []);
      } catch {
        setApplicationsState([]);
      }
    }

    refreshMeta();
    refreshApplications();
    const intervalId = window.setInterval(refreshMeta, 3000);
    const applicationsIntervalId = window.setInterval(refreshApplications, 6000);

    if (!api?.app?.getMeta) {
      setStatus('Renderer mode active. Desktop system details are partially estimated.');
    }

    return () => {
      window.clearInterval(intervalId);
      window.clearInterval(applicationsIntervalId);
    };
  }, []);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.chats, JSON.stringify(chats));
  }, [chats]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.messages, JSON.stringify(chatMessages));
  }, [chatMessages]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.projects, JSON.stringify(projects));
  }, [projects]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.settings, JSON.stringify(runtimeSettings));
  }, [runtimeSettings]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.page, page);
  }, [page]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEYS.seenUpdateVersion, seenUpdateVersion);
  }, [seenUpdateVersion]);

  useEffect(() => {
    if (page === 'updates' && updateFeed?.latestVersion) {
      setSeenUpdateVersion(String(updateFeed.latestVersion));
    }
  }, [page, updateFeed?.latestVersion]);

  useEffect(() => {
    const latestVersion = String(updateFeed?.latestVersion || '');
    const updateReady = Boolean(updateFeed?.readyToInstall);
    if (!updateFeed?.updateAvailable || !latestVersion || (!updateReady && latestVersion === seenUpdateVersion)) {
      return;
    }
    const announceKey = `${latestVersion}:${updateReady ? 'ready' : 'available'}`;
    if (announcedUpdateVersionRef.current === announceKey) {
      return;
    }

    announcedUpdateVersionRef.current = announceKey;
    setStatus(
      updateReady
        ? `Nov\u00e1 verze ${latestVersion} je p\u0159ipraven\u00e1. M\u016f\u017ee\u0161 d\u00e1t Restart & Update.`
        : `Je tu nov\u00fd update ${latestVersion}. LunaAI ho p\u0159ipravuje na pozad\u00ed.`
    );
  }, [seenUpdateVersion, updateFeed?.latestVersion, updateFeed?.readyToInstall, updateFeed?.updateAvailable]);

  useEffect(() => {
    if (currentChatId) {
      window.localStorage.setItem(STORAGE_KEYS.currentChatId, currentChatId);
    } else {
      window.localStorage.removeItem(STORAGE_KEYS.currentChatId);
    }
  }, [currentChatId]);

  const filteredChats = useMemo(() => {
    const query = search.trim().toLowerCase();
    return chats
      .filter((chat) => !chat.archived && !trashedChatIds.includes(chat.id))
      .filter((chat) => (query ? chat.title.toLowerCase().includes(query) : true))
      .sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || a.title.localeCompare(b.title));
  }, [chats, search, trashedChatIds]);

  const regularChats = useMemo(() => filteredChats.filter((chat) => !chat.projectId), [filteredChats]);
  const visibleProjects = useMemo(() => projects.filter((project) => !project.archived).sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || (a.title || '').localeCompare(b.title || '')), [projects]);


  function applyChatState(result, overrideMessages = null) {
    if (!result?.ok) return false;
    if (Array.isArray(result.chats)) {
      setChats(current => result.chats.map(chat => { const previous = current.find(item => item.id === chat.id); return previous ? { ...chat, pinned: previous.pinned, archived: previous.archived } : chat; }));
    }
    if (typeof result.currentChatId === 'string') {
      setCurrentChatId(result.currentChatId);
    }
    setPendingAction({
      active: Boolean(result?.pendingAction?.active),
      title: String(result?.pendingAction?.title || ''),
    });
    if (typeof result?.observeModeEnabled === 'boolean') {
      setObserveModeEnabled(result.observeModeEnabled);
    }
    if (result?.lastObservation && typeof result.lastObservation === 'object') {
      setDesktopObservation(result.lastObservation);
    }
    if (result?.observation && typeof result.observation === 'object') {
      setDesktopObservation(result.observation);
    }
    if (Array.isArray(overrideMessages) && typeof result.currentChatId === 'string') {
      setChatMessages((current) => ({
        ...current,
        [result.currentChatId]: overrideMessages,
      }));
      return true;
    }
    if (Array.isArray(result.messages) && typeof result.currentChatId === 'string') {
      setChatMessages((current) => ({
        ...current,
        [result.currentChatId]: result.messages,
      }));
    }
    return true;
  }

  function applyActionEnginePendingState(result) {
    const pending = result?.pendingAction || null;
    if (!pending?.active) {
      setActionEnginePending({ active: false, title: '' });
      return false;
    }

    const action = pending.action || {};
    const title = pending.title
      || `${action.type || 'Action Engine'}${action.target ? ` -> ${action.target}` : ''}`;
    setActionEnginePending({
      active: true,
      title,
      source: 'action-engine',
      message: pending.message || '',
    });
    return true;
  }

  function applyBackendChatState(result) {
    return applyChatState(result);
  }

  async function requestDesktopObservation(includeScreenshot = false, { silent = false } = {}) {
    const api = window.lunaDesktop?.luna;
    if (!api?.observeDesktop) {
      if (!silent) {
        setChatError({ message: 'Snímek obrazovky je dostupný v desktopové aplikaci PGEX.' });
      }
      return null;
    }

    try {
      setEyesBusy(true);
      const result = await api.observeDesktop({ includeScreenshot });
      applyBackendChatState(result);

      const context = String(result?.context || '').trim();
      if (context) {
        setPendingDesktopContext({
          context,
          includeScreenshot,
          summary: String(result?.summary || '').trim(),
        });
      }

      const screenshotPath = String(result?.observation?.screenshot_path || '').trim();
      if (includeScreenshot && screenshotPath) {
        const previewDataUrl = await readLocalPreviewDataUrl(screenshotPath);
        setAttachment((current) => {
          if (current?.previewUrl?.startsWith('blob:')) URL.revokeObjectURL(current.previewUrl);
          return {
            name: screenshotPath.split(/[/\\]/).pop() || 'desktop.png',
            type: 'image/png',
            path: screenshotPath,
            source: 'desktop-capture',
            previewUrl: previewDataUrl || toLocalFileUrl(screenshotPath),
          };
        });
      }

      if (!silent) {
        const detail = String(result?.observation?.detail || '').trim();
        if (includeScreenshot && !screenshotPath) {
          setChatError({ message: detail || 'Snímek obrazovky se nepodařilo pořídit.' });
        } else {
          setStatus(includeScreenshot
            ? 'Aktualni obrazovka je pripravena jako sdileny kontext pro dalsi zpravu.'
            : 'Desktop context jsem nacetla pro dalsi zpravu.');
        }
      }
      return result;
    } catch {
      if (!silent) {
        setChatError({ message: 'Obrazovku se nepodařilo načíst. Zkus pořídit snímek znovu.' });
      }
      return null;
    } finally {
      setEyesBusy(false);
    }
  }

  async function updateObserveMode(nextEnabled, { silent = false } = {}) {
    const api = window.lunaDesktop?.luna;
    if (!api?.setObserveMode) {
      if (!silent) {
        setStatus('Observe mode works only inside the Electron desktop shell.');
      }
      return null;
    }

    try {
      setEyesBusy(true);
      const result = await api.setObserveMode(nextEnabled);
      applyBackendChatState(result);
      let initialObservation = null;
      if (nextEnabled) {
        initialObservation = await requestDesktopObservation(true, { silent: true });
      }
      if (!silent) {
        const screenshotPath = String(initialObservation?.observation?.screenshot_path || '').trim();
        if (nextEnabled && screenshotPath) {
          setStatus('Observe mode je zapnuty a aktualni obrazovka je nactena.');
        } else {
          setStatus(String(result?.response || (nextEnabled ? 'Observe mode zapnuty.' : 'Observe mode vypnuty.')));
        }
      }
      return result;
    } catch {
      if (!silent) {
        setStatus('Observe mode change failed.');
      }
      return null;
    } finally {
      setEyesBusy(false);
    }
  }


  useEffect(() => {
    const api = window.lunaDesktop?.updates;

    async function loadUpdateFeed() {
      if (!api?.getFeed) {
        setUpdateFeed(buildFallbackUpdateFeed(updates, appMeta.version));
        return;
      }

      try {
        const nextFeed = api.prepare ? await api.prepare() : await api.getFeed();
        setUpdateFeed({
          ...buildFallbackUpdateFeed(updates, appMeta.version),
          ...nextFeed,
          entries: Array.isArray(nextFeed?.entries) && nextFeed.entries.length ? nextFeed.entries : updates,
          currentVersion: nextFeed?.currentVersion || appMeta.version || '0.1.0',
        });
      } catch {
        setUpdateFeed(buildFallbackUpdateFeed(updates, appMeta.version));
      }
    }

    loadUpdateFeed();
    const intervalId = window.setInterval(loadUpdateFeed, 300000);
    return () => window.clearInterval(intervalId);
  }, [appMeta.version]);

  useEffect(() => {
    const api = window.lunaDesktop?.luna;
    if (!api?.getState) return;

    let cancelled = false;

    async function loadChatState() {
      try {
        const result = await api.getState();
        if (cancelled) return;
        if (applyBackendChatState(result)) {
          setStatus('Luna backend chat connected.');
        }
      } catch {
        // keep local fallback state
      }
    }

    loadChatState();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const api = window.lunaDesktop?.actionEngine;
    if (!api?.getPending) return;

    let cancelled = false;

    async function loadActionEnginePending() {
      const result = await api.getPending().catch(() => null);
      if (!cancelled && result?.ok) {
        applyActionEnginePendingState(result);
      }
    }

    loadActionEnginePending();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const api = window.lunaDesktop?.luna;
    if (!api?.observeDesktop || page !== 'vision' || !observeModeEnabled) return undefined;

    let cancelled = false;

    const refresh = async (includeScreenshot = false) => {
      const result = await api.observeDesktop({ includeScreenshot }).catch(() => null);
      if (cancelled || !result?.ok) return;
      applyBackendChatState(result);
    };

    refresh(true);
    const intervalId = window.setInterval(() => refresh(true), 5000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [page, observeModeEnabled]);

  useEffect(() => {
    if (!applicationsState.length) {
      setSelectedApplicationId('');
      return;
    }
    setSelectedApplicationId((current) => (
      current && applicationsState.some((item) => item.id === current)
        ? current
        : applicationsState[0].id
    ));
  }, [applicationsState]);

  useEffect(() => {
    const actionApi = window.lunaDesktop?.actionEngine;
    if (!actionApi?.onInternalAction) return undefined;

    return actionApi.onInternalAction((payload) => {
      const action = payload?.action;
      if (!action?.target) return;

      switch (action.target) {
        case 'open-vision-panel':
          setPage('chat');
          setStatus('Vision panel je připravený pro screenshoty, dokumenty a systémový kontext.');
          break;
        case 'capture-screenshot':
          setPage('chat');
          requestDesktopObservation(true);
          break;
        case 'chat':
        case 'projects':
        case 'updates':
        case 'settings':
          setPage(action.target);
          setStatus(`Přepínám interní panel na ${action.target}.`);
          break;
        default:
          break;
      }
    });
  }, []);

  function appendMessages(chatId, nextMessages) {
    setChatMessages((current) => ({
      ...current,
      [chatId]: [...(current[chatId] || []), ...nextMessages],
    }));
  }

  function ensureActiveChat() {
    if (currentChatId) return currentChatId;
    const chatId = `chat-${Date.now()}`;
    const newChat = { id: chatId, title: 'New Chat', pinned: false, archived: false, kind: 'chat' };
    setChats((current) => [newChat, ...current]);
    setCurrentChatId(chatId);
    setChatMessages((current) => ({ ...current, [chatId]: [] }));
    return chatId;
  }

  async function handleSend(overrideText = '') {
    const safeOverrideText = typeof overrideText === 'string' ? overrideText : '';
    const text = normalizeTransportText(safeOverrideText || composer).trim();
    if ((!text && !attachment?.name) || sendLockRef.current || chatBusy || eyesBusy) return;

    const api = window.lunaDesktop?.luna;
    if (!api?.sendMessage) {
      setChatError({ message: 'Připojení k Luně není dostupné. Otevři PGEX jako desktopovou aplikaci.' });
      return;
    }
    if (attachment && !attachment.path) {
      setChatError({ message: 'Přílohu se nepodařilo načíst. Odeber ji a vyber soubor znovu.' });
      return;
    }

    // Capture this request before clearing the composer. A new draft may be
    // written while awaiting the response and must never be cleared afterward.
    const draft = {
      text,
      attachment: attachment ? { ...attachment, previewUrl: '' } : null,
      context: pendingDesktopContext,
    };
    const baseText = text || 'Prosím zpracuj přiložený soubor.';
    const decoratedText = attachment?.name
      ? `${baseText}\n\n[Příloha: ${normalizeTransportText(attachment.name)}]`
      : baseText;
    const activeChatId = ensureActiveChat();
    const filePaths = attachment?.path ? [attachment.path] : [];
    const extraContext = [
      String(pendingDesktopContext?.context || '').trim(),
    ].filter(Boolean).join('\n\n');

    sendLockRef.current = true;
    setChatBusy(true);
    setChatError(null);
    setComposer('');
    setAttachment(null);
    setPendingDesktopContext(null);
    setPage('chat');
    setSendingMessage({ id: `sending-${Date.now()}`, chatId: activeChatId, role: 'user', author: 'Ty', content: decoratedText });
    setThinkingState(createThinkingState(baseText));
    try {
      const result = await api.sendMessage({
        chatId: activeChatId,
        text: decoratedText,
        filePaths,
        extraContext,
      });
      if (!result?.ok) {
        setChatError({ message: result?.message || 'Luna nevrátila odpověď. Zkontroluj připojení a nastavení modelu.', draft });
        setThinkingState(idleThinkingState);
        return;
      }
      handleBackendResponseResult(result, 'Odpověď je připravená.');
    } catch {
      setChatError({ message: 'Spojení s Lunou se nepodařilo. Zprávu můžeš vrátit k úpravě a odeslat znovu.', draft });
      setThinkingState(idleThinkingState);
    } finally {
      setSendingMessage(null);
      sendLockRef.current = false;
      setChatBusy(false);
      setThinkingState(idleThinkingState);
    }
  }

  function restoreFailedDraft() {
    if (!chatError?.draft || composer.trim() || attachment) return;
    setComposer(chatError.draft.text);
    setAttachment(chatError.draft.attachment);
    setPendingDesktopContext(chatError.draft.context);
    setChatError(null);
  }

  function handleBackendResponseResult(result, successStatus) {
    if (!result?.ok) {
      setThinkingState(idleThinkingState);
      setStatus(result?.message || 'Luna backend did not return a valid reply.');
      return false;
    }

    applyBackendChatState(result);
    setThinkingState(idleThinkingState);
    setStatus(successStatus);
    return true;
  }

  async function handlePendingActionDecision(kind) {
    const lunaApi = window.lunaDesktop?.luna;
    const actionApi = window.lunaDesktop?.actionEngine;

    if (!pendingAction?.active && actionEnginePending?.active && actionApi) {
      setChatBusy(true);
      setThinkingState({ visible: true, lunaActive: true, xenoActive: true });
      try {
        const result = kind === 'confirm'
          ? await actionApi.confirmPending()
          : await actionApi.cancelPending();
        applyActionEnginePendingState(result);
        setStatus(result?.message || (kind === 'confirm' ? 'Action Engine request executed.' : 'Action Engine request cancelled.'));
      } catch {
        setStatus(kind === 'confirm' ? 'Action Engine confirmation failed.' : 'Action Engine cancellation failed.');
      } finally {
        setChatBusy(false);
        setThinkingState(idleThinkingState);
      }
      return;
    }

    if (!lunaApi) return;

    setChatBusy(true);
    setThinkingState({ visible: true, lunaActive: true, xenoActive: false });
    try {
      const result = kind === 'confirm'
        ? await lunaApi.confirmPendingAction()
        : await lunaApi.cancelPendingAction();
      const handled = handleBackendResponseResult(result, kind === 'confirm' ? 'Akce byla potvrzena.' : 'Akce byla zrusena.');
      if (kind === 'cancel' && handled) {
        const backendMessages = Array.isArray(result?.messages) ? result.messages : [];
        const lastBackendMessage = backendMessages[backendMessages.length - 1];
        if (lastBackendMessage?.role !== 'assistant') {
          const targetChatId = result?.currentChatId || currentChatId;
          appendMessages(targetChatId, [
            { id: `assistant-${Date.now()}`, role: 'assistant', author: 'Luna', content: 'Luna: Akci jsem zrusila.' },
          ]);
        }
      }
    } catch {
      setStatus(kind === 'confirm' ? 'Potvrzeni akce selhalo.' : 'Zruseni akce selhalo.');
    } finally {
      setChatBusy(false);
      setThinkingState(idleThinkingState);
    }
  }

  async function handleWindowAction(action) {
    const api = window.lunaDesktop?.window;

    if (api) {
      if (action === 'minimize') await api.minimize();
      if (action === 'maximize') await api.maximize();
      if (action === 'close') await api.close();
      if (action === 'hide-to-tray' && api.hideToTray) {
        const result = await api.hideToTray();
        setStatus(result?.message || 'LunaAI is still running in the tray.');
      }
      return;
    }

    if (action === 'maximize') {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen?.();
        setStatus('Preview mode: fullscreen toggled because Electron window controls are not attached.');
      } else {
        document.exitFullscreen?.();
        setStatus('Preview mode: fullscreen restored.');
      }
      return;
    }

    if (action === 'minimize') {
      setStatus('Minimize works only inside the Electron desktop window.');
      return;
    }

    if (action === 'close') {
      window.close();
      setStatus('Close works only inside the Electron desktop window.');
    }
  }

  async function handleNewChat() {
    const api = window.lunaDesktop?.luna;
    if (api?.createChat) {
      try {
        const result = await api.createChat('New chat');
        if (applyBackendChatState(result)) {
          setStatus('New conversation created.');
        }
      } catch {
        setStatus('Creating a backend chat failed.');
      }
    } else {
      const chatId = `chat-${Date.now()}`;
      const newChat = { id: chatId, title: 'New Chat', pinned: false, archived: false, kind: 'chat' };
      setChats((current) => [newChat, ...current]);
      setCurrentChatId(chatId);
      setChatMessages((current) => ({ ...current, [chatId]: [] }));
      setStatus('New conversation created.');
    }
    setComposer('');
    setAttachment(null);

    setPage('chat');
  }

  async function handleChatOpen(chatId) {
    const api = window.lunaDesktop?.luna;
    if (api?.switchChat) {
      try {
        const result = await api.switchChat(chatId);
        applyBackendChatState(result);
      } catch {
        setCurrentChatId(chatId);
      }
    } else {
      setCurrentChatId(chatId);
    }
    setPage('chat');
    setStatus('Conversation ready.');
  }

  function handleChatContext(event, chat) {
    event.preventDefault();
    setContextMenu({ visible: true, x: event.clientX, y: event.clientY, kind: 'chat', targetId: chat.id, title: chat.title, saved: false });
  }

  function handleProjectContext(event, project) {
    event.preventDefault();
    setContextMenu({ visible: true, x: event.clientX, y: event.clientY, kind: 'project', targetId: project.id, title: project.title, saved: false });
  }

  function closeContextMenu() {
    setContextMenu((current) => ({ ...current, visible: false }));
  }

  function renameChat() {
    const next = window.prompt('Rename chat', contextMenu.title);
    if (!next) return closeContextMenu();

    if (contextMenu.kind === 'project') {
      let linkedChatId = '';
      setProjects((current) => current.map((project) => {
        if (project.id !== contextMenu.targetId) return project;
        linkedChatId = project.chatId || '';
        return { ...project, title: next };
      }));
      if (linkedChatId) {
        setChats((current) => current.map((chat) => (chat.id === linkedChatId ? { ...chat, title: next } : chat)));
      }
      setStatus('Project title updated.');
      closeContextMenu();
      return;
    }

    const api = window.lunaDesktop?.luna;
    if (api?.renameChat) {
      api.renameChat(contextMenu.targetId, next)
        .then((result) => {
          applyBackendChatState(result);
          setStatus('Chat title updated.');
        })
        .catch(() => {
          setChats((current) => current.map((chat) => (chat.id === contextMenu.targetId ? { ...chat, title: next } : chat)));
          setStatus('Chat title updated locally.');
        });
      closeContextMenu();
      return;
    }

    setChats((current) => current.map((chat) => (chat.id === contextMenu.targetId ? { ...chat, title: next } : chat)));
    setStatus('Chat title updated.');
    closeContextMenu();
  }

  function pinChat() {
    if (contextMenu.kind === 'project') {
      setProjects((current) => current.map((project) => (project.id === contextMenu.targetId ? { ...project, pinned: !project.pinned } : project)));
      setStatus('Project pin state updated.');
      closeContextMenu();
      return;
    }

    setChats((current) => current.map((chat) => (chat.id === contextMenu.targetId ? { ...chat, pinned: !chat.pinned } : chat)));
    setStatus('Chat pin state updated.');
    closeContextMenu();
  }

  function deleteChat() {
    if (contextMenu.kind === 'project') {
      const linkedProject = projects.find((project) => project.id === contextMenu.targetId);
      const linkedChatId = linkedProject?.chatId || '';

      setProjects((current) => current.filter((project) => project.id !== contextMenu.targetId));
      if (linkedChatId) {
        const nextChats = chats.filter((chat) => chat.id !== linkedChatId);
        setChats(nextChats);
        setChatMessages((current) => {
          const next = { ...current };
          delete next[linkedChatId];
          return next;
        });
        if (currentChatId === linkedChatId) {
          setCurrentChatId(nextChats[0]?.id ?? '');
        }
      }
      setStatus('Project removed from the workspace.');
      closeContextMenu();
      return;
    }

    setTrashedChatIds(current => [...new Set([...current, contextMenu.targetId])]);
    if (currentChatId === contextMenu.targetId) setCurrentChatId('');
    setPage('history');
    setStatus('Konverzace byla přesunuta do koše.');
    closeContextMenu();
  }

  function archiveChat() {
    if (contextMenu.kind === 'project') {
      setProjects((current) => current.map((project) => (project.id === contextMenu.targetId ? { ...project, archived: true } : project)));
      setStatus('Project archived from Projects.');
      closeContextMenu();
      return;
    }

    setChats((current) => current.map((chat) => (chat.id === contextMenu.targetId ? { ...chat, archived: true } : chat)));
    setStatus('Chat archived from the main sidebar.');
    closeContextMenu();
  }

  function handleOpenNotifications() {
    setNotificationsOpen((current) => !current);
  }

  function handleNotificationSelect(item) {
    if (!item) return;

    if (item.kind === 'update') {
      setSeenUpdateVersion(String(item.version || updateFeed?.latestVersion || ''));
      setPage('updates');
      setNotificationsOpen(false);
      setStatus(`Nov\u00e1 verze ${item.version || updateFeed?.latestVersion || ''} je p\u0159ipraven\u00e1 v Updates.`);
      return;
    }

    setNotificationsOpen(false);
  }

  function handleInputAction(action, payload) {
    if (action === 'file' && payload) {
      try {
        const path = window.lunaDesktop?.files?.getPathForFile?.(payload);
        if (!path) throw new Error('missing path');
        setAttachment({
          name: payload.name,
          type: payload.type || '',
          path,
          previewUrl: payload.type?.startsWith('image/') ? URL.createObjectURL(payload) : '',
        });
        setPendingDesktopContext(null);
        setChatError(null);
      } catch {
        setChatError({ message: 'Soubor se nepodařilo přiložit. Otevři desktopovou aplikaci PGEX a vyber soubor z disku.' });
      }
      return;
    }
    if (action === 'screenshot') requestDesktopObservation(true);
  }

  async function handleSaveApplicationPath(appItem, nextPath) {
    if (!appItem?.key) return;

    const api = window.lunaDesktop?.apps;
    if (!api?.updatePath) {
      setStatus('Application path editing works only inside the Electron desktop shell.');
      return;
    }

    try {
      const result = await api.updatePath(appItem.key, nextPath);
      if (Array.isArray(result?.apps)) {
        setApplicationsState(result.apps);
      }
      setStatus(result?.message || `${appItem.title} path saved.`);
    } catch {
      setStatus(`${appItem.title} path could not be saved.`);
    }
  }

  async function handleOpenApplication(appItem) {
    if (!appItem?.key) return;

    const api = window.lunaDesktop?.apps;
    if (!api?.launch) {
      setStatus('Application launch works only inside the Electron desktop shell.');
      return;
    }

    try {
      const result = await api.launch(appItem.key);
      setStatus(result?.message || `${appItem.title} action finished.`);
      if (api.list) {
        const nextApps = await api.list();
        setApplicationsState(Array.isArray(nextApps) ? nextApps : []);
      }
    } catch {
      setStatus(`${appItem.title} could not be launched.`);
    }
  }

  function handleRuntimeSettings(nextPartial) {
    setRuntimeSettings((current) => ({ ...current, ...nextPartial }));
    setStatus('Runtime resource limits adjusted.');
  }

  async function handleSaveRuntimeSettings() {
    window.localStorage.setItem(STORAGE_KEYS.settings, JSON.stringify(runtimeSettings));

    try {
      const api = window.lunaDesktop?.settings;
      if (api?.saveRuntime) {
        const saved = await api.saveRuntime(runtimeSettings);
        setRuntimeSettings((current) => ({ ...current, ...saved }));
        setStatus('Runtime resource limits saved to desktop settings.');
        return;
      }
    } catch {
      setStatus('Runtime settings were saved locally, but desktop sync failed.');
      return;
    }

    setStatus('Runtime resource limits saved.');
  }

  function handleOpenProjectModal() {
    setProjectModalOpen(true);
  }

  function handleCloseProjectModal() {
    setProjectModalOpen(false);
  }

  function handleCreateProject() {
    const name = projectName.trim();
    if (!name) return;

    const chatId = `project-chat-${Date.now()}`;
    const projectId = `p-${Date.now()}`;

    const typeLabels = {
      investing: 'Track goals and decisions in one place',
      home: 'Organize tasks, notes, and practical follow-ups',
      writing: 'Keep drafts, structure, and research aligned',
      travel: 'Collect plans, routes, and trip context',
    };

    const createdProject = {
      id: projectId,
      title: name,
      phase: projectType,
      nextStep: typeLabels[projectType] || 'Structured LunaAI project',
      tasks: 0,
      chatId,
    };

    setProjects((current) => [createdProject, ...current]);
    setChats((current) => [{ id: chatId, title: name, pinned: false, archived: false, projectId, kind: 'project' }, ...current]);
    setChatMessages((current) => ({ ...current, [chatId]: [] }));
    setCurrentChatId(chatId);
    setProjectModalOpen(false);
    setProjectName('');
    setProjectType('investing');
    setPage('chat');
    setStatus(`Project created: ${name}`);
  }

  function handleOpenProjectChat(project) {
    let targetChatId = project.chatId;

    if (!targetChatId) {
      targetChatId = `project-chat-${Date.now()}`;
      setProjects((current) => current.map((item) => (item.id === project.id ? { ...item, chatId: targetChatId } : item)));
      setChats((current) => [{ id: targetChatId, title: project.title, pinned: false, archived: false, projectId: project.id, kind: 'project' }, ...current]);
      setChatMessages((current) => ({ ...current, [targetChatId]: current[targetChatId] || [] }));
    } else if (!chats.some((chat) => chat.id === targetChatId)) {
      setChats((current) => [{ id: targetChatId, title: project.title, pinned: false, archived: false, projectId: project.id, kind: 'project' }, ...current]);
    }

    setCurrentChatId(targetChatId);
    setPage('chat');
    setStatus(`Project channel ready: ${project.title}`);
  }

  const contextMenuLabels = { rename: 'Rename', pin: 'Pin Chat', delete: 'Delete', archive: 'Archive' };

  async function deleteSelectedTrash() {
    const ids = selectedTrashIds.filter(id => trashedChatIds.includes(id) && chats.some(chat => chat.id === id));
    if (trashBusy || !ids.length) return;
    if (!window.confirm(`Trvale odstranit vybrané konverzace (${ids.length})?\n\nZprávy nebude možné obnovit z koše.`)) return;
    setTrashBusy(true);
    let failed = false;
    try {
      for (const id of ids) {
        const api = window.lunaDesktop?.luna;
        if (api?.deleteChat) {
          const result = await api.deleteChat(id);
          if (!result?.ok) throw new Error('Delete failed');
          applyBackendChatState(result);
        }
        setChats(items => items.filter(item => item.id !== id));
        setChatMessages(items => { const next = {...items}; delete next[id]; return next; });
        setTrashedChatIds(items => items.filter(item => item !== id));
        setSelectedTrashIds(items => items.filter(item => item !== id));
        setProjects(items => items.map(project => project.chatId === id ? {...project, chatId: ''} : project));
        setCurrentChatId(current => current === id ? '' : current);
      }
    } catch { failed = true; }
    finally { setTrashBusy(false); }
    if (failed) window.alert('Některé konverzace se nepodařilo odstranit. Neodstraněné položky zůstávají v koši.');
  }

  function renderMain() {
    if (['history', 'favorites', 'trash'].includes(page)) {
      const inTrash = page === 'trash';
      const rows = chats.filter(chat => inTrash === trashedChatIds.includes(chat.id))
        .filter(chat => page !== 'favorites' || chat.pinned)
        .filter(chat => !search.trim() || chat.title.toLowerCase().includes(search.trim().toLowerCase()));
      const title = inTrash ? 'Koš' : page === 'favorites' ? 'Oblíbené' : 'Všechny konverzace';
      return <section className="history-page"><h1>{title}</h1><p>{inTrash ? 'Smazané konverzace můžeš obnovit. Zprávy zůstávají zachované.' : 'Vyhledej rozhovor a pokračuj tam, kde jsi skončil.'}</p>
        <input className="sidebar-search" aria-label="Hledat v historii" placeholder={inTrash ? "Hledat v koši…" : "Hledat v historii…"} value={search} onChange={event => setSearch(event.target.value)}/>
        {inTrash && <div className="trash-toolbar"><label><input type="checkbox" disabled={trashBusy || !rows.length} checked={rows.length > 0 && rows.every(chat => selectedTrashIds.includes(chat.id))} onChange={event => setSelectedTrashIds(event.target.checked ? rows.map(chat => chat.id) : [])}/> Vybrat vše</label><span>Vybráno: {selectedTrashIds.filter(id => trashedChatIds.includes(id)).length}</span><button className="secondary-button" disabled={trashBusy || !selectedTrashIds.length} onClick={() => {setTrashedChatIds(ids => ids.filter(id => !selectedTrashIds.includes(id)));setSelectedTrashIds([]);}}>Obnovit</button><button className="secondary-button permanent-delete" disabled={trashBusy || !selectedTrashIds.length} onClick={deleteSelectedTrash}>{trashBusy ? 'Odstraňuji…' : 'Odstranit natrvalo'}</button></div>}
        <div className="history-list">{rows.map(chat => <article key={chat.id} className={`history-item ${inTrash ? 'trash-item' : ''}`}>
        {inTrash && <input type="checkbox" aria-label={`Vybrat ${chat.title}`} disabled={trashBusy} checked={selectedTrashIds.includes(chat.id)} onChange={event => setSelectedTrashIds(ids => event.target.checked ? [...new Set([...ids, chat.id])] : ids.filter(id => id !== chat.id))}/>}<button className="history-open" disabled={inTrash} onClick={() => handleChatOpen(chat.id)}><strong>{chat.title}</strong><small>{chat.projectId ? 'Projektová konverzace' : 'Konverzace s Lunou'}</small></button>
        {inTrash ? null : <><button className="history-star" aria-label={chat.pinned ? 'Odebrat z oblíbených' : 'Přidat do oblíbených'} onClick={() => setChats(items => items.map(item => item.id === chat.id ? {...item, pinned: !item.pinned} : item))}>{chat.pinned ? '★' : '☆'}</button><button className="secondary-button" onClick={() => {setTrashedChatIds(ids => [...new Set([...ids, chat.id])]); if (currentChatId === chat.id) setCurrentChatId('');}}>Do koše</button></>}
        </article>)}</div>{rows.length === 0 && <p className="history-empty">{inTrash ? 'Koš je prázdný.' : 'Žádné odpovídající konverzace.'}</p>}</section>;
    }

    if (page === 'chat') {
      const isEmptyChat = messages.length === 0;
      const combinedPendingAction = pendingAction?.active ? pendingAction : actionEnginePending;

      return (
        <div className={`chat-page ${isEmptyChat ? 'is-empty' : ''}`} >
          <div className="conversation-layout">
          <ChatArea
            messages={sendingMessage?.chatId === currentChatId ? [...messages, sendingMessage] : messages}
            chatId={currentChatId}
            thinkingState={thinkingState}
            pendingAction={combinedPendingAction}
            onConfirmPendingAction={() => handlePendingActionDecision('confirm')}
            onCancelPendingAction={() => handlePendingActionDecision('cancel')}
          />
          </div>
          {chatError && (
            <div className="chat-error" role="alert">
              <p>{chatError.message}</p>
              <div>
                {chatError.draft && <button type="button" disabled={Boolean(composer.trim() || attachment)} onClick={restoreFailedDraft}>Vrátit zprávu k úpravě</button>}
                <button type="button" onClick={() => setChatError(null)} aria-label="Zavřít chybu">Zavřít</button>
              </div>
              {chatError.draft && Boolean(composer.trim() || attachment) && <small>Pro obnovení zprávy nejprve odešli nebo vyprázdni aktuální rozepsanou zprávu.</small>}
            </div>
          )}
          <ChatInput
            busy={chatBusy}
            attachmentBusy={eyesBusy}
            value={composer}
            onChange={setComposer}
            onSend={handleSend}
            onAction={handleInputAction}
            attachment={attachment}
            onClearAttachment={() => {
              setAttachment((current) => {
                if (current?.previewUrl?.startsWith('blob:')) URL.revokeObjectURL(current.previewUrl);
                return null;
              });
              if (attachment?.source === 'desktop-capture') {
                setPendingDesktopContext(null);
              }
            }}
            centered={isEmptyChat}
          />
        </div>
      );
    }

    if (page === 'vision') {
      return (
        <EyesPage
          title={pageData.title}
          subtitle={pageData.subtitle}
          observation={desktopObservation}
          previewUrl={desktopPreviewUrl}
          observeModeEnabled={observeModeEnabled}
          busy={eyesBusy}
          onObserveDesktop={() => requestDesktopObservation(false)}
          onCaptureScreen={() => requestDesktopObservation(true)}
        />
      );
    }
    if (page === 'projects') {
      return <SectionPage title={pageData.title} subtitle={pageData.subtitle} items={visibleProjects} actionLabel="Nový projekt" onAction={handleOpenProjectModal} onItemClick={handleOpenProjectChat} onItemContext={handleProjectContext} />;
    }
    if (page === 'updates') {
      return (
        <UpdatesPage
          title={pageData.title}
          subtitle={pageData.subtitle}
          items={updates}
          currentVersion={appMeta.version}
          initialFeed={updateFeed}
          onFeedChange={setUpdateFeed}
          onStatusChange={setStatus}
        />
      );
    }
    if (page === 'settings' || page === 'applications') {
      return (
        <SettingsPage
          settings={runtimeSettings}
          onChange={handleRuntimeSettings}
          onSave={handleSaveRuntimeSettings}
          appMeta={appMeta}
          applications={applicationsState}
          selectedAppId={selectedApplicationId}
          onSelectApp={setSelectedApplicationId}
          onOpenApp={handleOpenApplication}
          onSavePath={handleSaveApplicationPath}
        />
      );
    }
    return <SectionPage title={pageData.title} subtitle={pageData.subtitle} items={updates} />;
  }

  return (
    <>
      <AppShell
        topbar={
          <TopBar
            collapsed={sidebarCollapsed}
            onToggleSidebar={() => setSidebarCollapsed((current) => !current)}
            onOpenNotifications={handleOpenNotifications}
            notificationCount={notificationCount}
            onWindowAction={handleWindowAction}
          />
        }
        sidebar={
          <Sidebar
            collapsed={sidebarCollapsed}
            search={search}
            onSearchChange={setSearch}
            currentPage={page}
            onSelectPage={setPage}
            regularChats={filteredChats}
            projects={visibleProjects}
            onProjectOpen={handleOpenProjectChat}
            onNewProject={handleOpenProjectModal}
            currentChatId={currentChatId}
            onNewChat={handleNewChat}
            onChatOpen={handleChatOpen}
            onChatContext={handleChatContext}
            onOpenSettings={() => setPage('settings')}
          />
        }
        main={renderMain()}
        notificationsPanel={
          <NotificationsPanel
            visible={notificationsOpen}
            items={notifications}
            onSelect={handleNotificationSelect}
            onClose={() => setNotificationsOpen(false)}
          />
        }
        contextMenu={
          <ContextMenu
            visible={contextMenu.visible}
            x={contextMenu.x}
            y={contextMenu.y}
            onRename={renameChat}
            onPin={pinChat}
            onDelete={deleteChat}
            onArchive={archiveChat}
            onClose={closeContextMenu}
            labels={contextMenuLabels}
            showArchive={true}
            showPin={true}
          />
        }
      />
      <ProjectModal
        visible={projectModalOpen}
        value={projectName}
        selectedType={projectType}
        onChange={setProjectName}
        onSelectType={setProjectType}
        onClose={handleCloseProjectModal}
        onCreate={handleCreateProject}
      />
    </>
  );
}
