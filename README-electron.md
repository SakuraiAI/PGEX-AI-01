# PGEX-AI-01 Electron Shell

This is a React + Electron desktop shell for PGEX-AI-01.

## Stack
- Electron
- React
- Vite
- Custom frameless desktop window
- Safe preload / IPC bridge

## Structure
- `electron/main.js` - Electron main process
- `electron/preload.cjs` - safe preload bridge
- `electron/services/` - smaller Electron service modules for settings, updates, apps, metrics, and Luna bridge
- `src/App.jsx` - root renderer shell
- `src/components/` - reusable UI pieces
- `src/layouts/` - shell layout
- `src/pages/` - section pages
- `src/sections/` - reusable page surface pieces
- `src/styles/theme.css` - black-and-white premium theme
- `.env.example` - environment-based model and API configuration template

## Included UI
- custom title bar
- collapsible sidebar
- chat workspace
- chat input surface
- right-click context menu for chats
- profile panel
- subtle AI orb / core visual
- sections for:
  - Search
  - New Chat
  - Gallery
  - Projects
  - Applications
  - Updates
  - Friends / Groups
  - Chat History
  - Settings

## Run
Install Node.js first, then:

```powershell
npm install
npm run dev
```

Production shell:

```powershell
npm run build
npm start
```

## Future integration
The preload bridge already exposes:
- window controls
- app metadata
- a placeholder IPC route for future Luna backend actions

This makes the shell ready for later connection to:
- Luna local backend
- Xeno reasoning
- agent execution layer
- desktop integrations
