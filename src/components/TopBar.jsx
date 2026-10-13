import lunaPortrait from '../assets/luna.jpg';

export default function TopBar({ collapsed, onToggleSidebar, onWindowAction, onOpenNotifications, notificationCount }) {
  return (
    <header className="topbar app-drag-region">
      <div className="topbar-left app-no-drag">
        <button type="button" className="topbar-toggle" onClick={onToggleSidebar} aria-label="Přepnout postranní panel" aria-expanded={!collapsed}>☰</button>
        <div className="assistant-identity"><img className="luna-avatar" src={lunaPortrait} alt="" /><span>PGEX</span></div>
      </div>
      <div className="topbar-right app-no-drag">
        {notificationCount > 0 && <button type="button" className="window-button" onClick={onOpenNotifications} aria-label={`Oznámení (${notificationCount})`}>♧ •</button>}
        <div className="window-controls">
          <button type="button" className="window-button" onClick={() => onWindowAction('minimize')} aria-label="Minimalizovat">−</button>
          <button type="button" className="window-button" onClick={() => onWindowAction('maximize')} aria-label="Maximalizovat">□</button>
          <button type="button" className="window-button is-close" onClick={() => onWindowAction('close')} aria-label="Zavřít">×</button>
        </div>
      </div>
    </header>
  );
}
