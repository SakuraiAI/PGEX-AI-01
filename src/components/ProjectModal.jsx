const projectTypes = [
  { id: 'investing', label: 'Investování' },
  { id: 'home', label: 'Domácí úkoly' },
  { id: 'writing', label: 'Psaní' },
  { id: 'travel', label: 'Cestování' },
];

export default function ProjectModal({ visible, value, selectedType, onChange, onSelectType, onClose, onCreate }) {
  if (!visible) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="project-modal" onClick={(event) => event.stopPropagation()}>
        <div className="project-modal-head">
          <div>
            <h2>Vytvořit projekt</h2>
          </div>
          <div className="project-modal-actions">
            <button type="button" className="modal-icon-button" aria-label="Zavřít" onClick={onClose}>×</button>
          </div>
        </div>

        <label className="project-field">
          <span>Název projektu</span>
          <input
            className="project-name-input"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder="Název tvého projektu"
          />
        </label>

        <div className="project-type-row">
          {projectTypes.map((type) => (
            <button
              key={type.id}
              type="button"
              className={`project-type-chip ${selectedType === type.id ? 'is-active' : ''}`}
              onClick={() => onSelectType(type.id)}
            >
              {type.label}
            </button>
          ))}
        </div>

        <div className="project-note">
          <p>Projekt ti pomůže uspořádat konverzace k jednomu tématu.</p>
        </div>

        <div className="project-modal-footer">
          <button type="button" className="primary-button project-create-button" onClick={onCreate} disabled={!value.trim()}>
            Vytvořit projekt
          </button>
        </div>
      </div>
    </div>
  );
}
