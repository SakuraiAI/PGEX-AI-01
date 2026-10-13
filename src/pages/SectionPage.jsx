import PanelCard from '../sections/PanelCard';

export default function SectionPage({ title, subtitle, items, actionLabel, onAction, onItemClick, onItemContext }) {
  return (
    <div className="section-page-grid is-simple">
      <PanelCard title={title} subtitle={subtitle}>
        {actionLabel && onAction ? (
          <div className="section-toolbar">
            <button type="button" className="secondary-button section-action-button" onClick={onAction}>
              {actionLabel}
            </button>
          </div>
        ) : null}
        {items.length === 0 && <p className="history-empty">Zatím tu nic není. Začni vytvořením projektu.</p>}
        <div className="stack-list">
          {items.map((item) => {
            const content = (
              <>
                <div>
                  <strong>{item.title || item.name}</strong>
                  <p>{item.meta || item.detail || item.nextStep || 'LunaAI system item'}</p>
                </div>
              </>
            );

            if (onItemClick) {
              return (
                <button
                  key={item.id}
                  type="button"
                  className="stack-card stack-card-button"
                  onClick={() => onItemClick(item)}
                  onContextMenu={onItemContext ? (event) => onItemContext(event, item) : undefined}
                >
                  {content}
                </button>
              );
            }

            return (
              <article
                key={item.id}
                className="stack-card"
                onContextMenu={onItemContext ? (event) => onItemContext(event, item) : undefined}
              >
                {content}
              </article>
            );
          })}
        </div>
      </PanelCard>

    </div>
  );
}
