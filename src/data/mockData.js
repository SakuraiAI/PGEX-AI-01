export const sidebarSections = [
  { key: 'vision', label: 'Vision' },
  { key: 'projects', label: 'Projects' },
  { key: 'friends', label: 'Friends' },
];

export const initialChats = [];

export const initialMessages = [];

export const projectCards = [];

export const applications = [
  { id: 'a-1', name: 'VS Code', detail: 'Connected workspace editor', status: 'Ready' },
  { id: 'a-2', name: 'Blender', detail: '3D and asset creation layer', status: 'Ready' },
  { id: 'a-3', name: 'Unreal Engine', detail: 'Real-time scene and game environment', status: 'Path missing' },
];

export const updates = [
  {
    id: 'u-1',
    title: 'System Upgrade Pass',
    detail: 'Trust layer, action registry, and memory quality were hardened across Luna, Xeno, and the agent flow.',
    status: 'Patch',
    version: '0.1.0',
    date: 'April 2, 2026',
    notes: [
      'Runtime resource limits now affect real Luna behavior instead of only local UI state.',
      'Project and chat flows were aligned into a cleaner shared shell.',
      'Electron desktop identity and internal system layout were refined.',
    ],
  },
  {
    id: 'u-2',
    title: 'Observe Layer',
    detail: 'Desktop observation now supports meaning, diffs, and agent handoff.',
    status: 'New',
    version: '0.1.0',
    date: 'April 1, 2026',
    notes: [
      'Luna can detect the active window, app meaning, and change summaries.',
      'Observe mode can now feed context into Luna and Xeno reasoning.',
      'The agent layer can use observation as a real execution step.',
    ],
  },
  {
    id: 'u-3',
    title: 'Voice Layer',
    detail: 'Microphone and voice loop shell were prepared for conversation mode.',
    status: 'Ready',
    version: '0.1.0',
    date: 'March 31, 2026',
    notes: [
      'Microphone input can be routed into Luna as text.',
      'Voice mode groundwork is prepared for a more personal loop later.',
      'The shell is ready for calmer speech output and listening states next.',
    ],
  },
];

export const friends = [
  { id: 'f-1', name: 'XenoAI', detail: 'Strategic sister layer for deep planning and hidden reasoning.', status: 'Linked' },
  { id: 'f-2', name: 'Task Agent', detail: 'Execution layer for local actions, files, apps, and workflow chains.', status: 'Ready' },
  { id: 'f-3', name: 'Luna Core', detail: 'Visible operator surface that translates system intelligence into clean interaction.', status: 'Online' },
];
