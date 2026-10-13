export default function NotificationsPanel({ visible, items, onSelect, onClose }) {
  if (!visible) return null;
  return (
    <div className={`notifications-panel ${visible ? 'is-open' : ''}`}>
      <div className="notifications-panel-card">
        <div className="notifications-panel-head">
          <div>
            <h3>{'Ozn\u00e1men\u00ed'}</h3>
            <p>{'Pozv\u00e1nky, \u017e\u00e1dosti a syst\u00e9mov\u00e9 ud\u00e1losti pro LunaAI.'}</p>
          </div>
          <button type="button" className="secondary-button notifications-close" onClick={onClose}>{'Zav\u0159\u00edt'}</button>
        </div>

        <div className="notifications-list">
          {items.length === 0 ? (
            <div className="notifications-empty">
              <strong>{'Zat\u00edm nic nov\u00e9ho'}</strong>
              <p>{'Nov\u00e9 pozv\u00e1nky, updatey a dal\u0161\u00ed ud\u00e1losti se objev\u00ed tady.'}</p>
            </div>
          ) : (
            items.map((item) => (
              <button
                key={item.id}
                type="button"
                className="notification-item notification-item-button"
                onClick={() => onSelect?.(item)}
              >
                <div className="notification-item-copy">
                  <strong>{item.title}</strong>
                  <p>{item.detail}</p>
                </div>
                <span className={`notification-kind is-${item.kind}`}>{item.label}</span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
