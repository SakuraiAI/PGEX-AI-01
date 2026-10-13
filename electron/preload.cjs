const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('lunaDesktop', {
  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    close: () => ipcRenderer.invoke('window:close'),
    hideToTray: () => ipcRenderer.invoke('window:hide-to-tray'),
    show: () => ipcRenderer.invoke('window:show'),
    showAssistantOverlay: () => ipcRenderer.invoke('window:show-assistant-overlay'),
    hideAssistantOverlay: () => ipcRenderer.invoke('window:hide-assistant-overlay'),
  },
  app: {
    getMeta: () => ipcRenderer.invoke('app:get-meta'),
  },
  shell: {
    openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
  },
  files: {
    getPathForFile: (file) => webUtils.getPathForFile(file),
    readAsDataUrl: (filePath) => ipcRenderer.invoke('files:read-as-data-url', filePath),
    writeTempDataUrl: (payload) => ipcRenderer.invoke('files:write-temp-data-url', payload),
  },
  settings: {
    getRuntime: () => ipcRenderer.invoke('settings:get-runtime'),
    saveRuntime: (payload) => ipcRenderer.invoke('settings:save-runtime', payload),
  },
  apps: {
    list: () => ipcRenderer.invoke('apps:list'),
    updatePath: (appKey, nextPath) => ipcRenderer.invoke('apps:update-path', appKey, nextPath),
    launch: (appKey) => ipcRenderer.invoke('apps:launch', appKey),
  },
  updates: {
    getFeed: () => ipcRenderer.invoke('updates:get-feed'),
    check: () => ipcRenderer.invoke('updates:check'),
    download: (downloadUrl) => ipcRenderer.invoke('updates:download', downloadUrl),
    prepare: () => ipcRenderer.invoke('updates:prepare'),
    restartAndInstall: () => ipcRenderer.invoke('updates:restart-and-install'),
  },
  actionEngine: {
    execute: (payload) => ipcRenderer.invoke('action-engine:execute', payload),
    getPending: () => ipcRenderer.invoke('action-engine:get-pending'),
    confirmPending: () => ipcRenderer.invoke('action-engine:confirm-pending'),
    cancelPending: () => ipcRenderer.invoke('action-engine:cancel-pending'),
    onInternalAction: (handler) => {
      if (typeof handler !== 'function') {
        return () => {};
      }
      const listener = (_event, payload) => handler(payload);
      ipcRenderer.on('action-engine:internal-ui', listener);
      return () => {
        ipcRenderer.removeListener('action-engine:internal-ui', listener);
      };
    },
  },
  agent: {
    execute: (payload) => ipcRenderer.invoke('agent:execute', payload),
  },
  luna: {
    getState: () => ipcRenderer.invoke('luna:get-state'),
    createChat: (title) => ipcRenderer.invoke('luna:create-chat', title),
    switchChat: (chatId) => ipcRenderer.invoke('luna:switch-chat', chatId),
    renameChat: (chatId, title) => ipcRenderer.invoke('luna:rename-chat', chatId, title),
    deleteChat: (chatId) => ipcRenderer.invoke('luna:delete-chat', chatId),
    sendMessage: (payload) => ipcRenderer.invoke('luna:send-message', payload),
    observeDesktop: (payload) => ipcRenderer.invoke('luna:observe-desktop', payload),
    analyzeVisual: (payload) => ipcRenderer.invoke('luna:analyze-visual', payload),
    observeSystem: (payload) => ipcRenderer.invoke('luna:observe-system', payload),
    transcribeAudio: (payload) => ipcRenderer.invoke('luna:transcribe-audio', payload),
    synthesizeSpeech: (payload) => ipcRenderer.invoke('luna:synthesize-speech', payload),
    setObserveMode: (enabled) => ipcRenderer.invoke('luna:set-observe-mode', enabled),
    confirmPendingAction: () => ipcRenderer.invoke('luna:confirm-pending-action'),
    cancelPendingAction: () => ipcRenderer.invoke('luna:cancel-pending-action'),
    futureAction: (payload) => ipcRenderer.invoke('luna:future-action', payload),
  },
});
