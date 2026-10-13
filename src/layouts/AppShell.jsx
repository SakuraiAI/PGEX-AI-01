export default function AppShell({ topbar, sidebar, main, notificationsPanel, contextMenu }) {
  return (
    <div className="app-shell">
      {topbar}
      <div className="app-shell-body">
        {sidebar}
        <main className="app-main">{main}</main>
      </div>
      {notificationsPanel}
      {contextMenu}
    </div>
  );
}
