import { useEffect, useState } from 'react';
import PanelCard from '../sections/PanelCard';

function ResourceSlider({ label, value, onChange, meta, accentLabel }) {
  return (
    <div className="settings-resource-card">
      <div className="settings-resource-head">
        <div>
          <strong>{label}</strong>
          <span>{accentLabel}</span>
        </div>
        <div className="settings-resource-value">{value}%</div>
      </div>
      <input
        className="settings-range"
        type="range"
        min="10"
        max="100"
        step="5"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <div className="settings-resource-meta">
        <span>{meta.primary}</span>
        <span>{meta.secondary}</span>
      </div>
    </div>
  );
}

function ApplicationsSettingsSection({
  items,
  selectedAppId,
  onSelectApp,
  onOpenApp,
  onSavePath,
}) {
  const selected = items.find((item) => item.id === selectedAppId) || items[0] || null;
  const [pathDraft, setPathDraft] = useState('');

  useEffect(() => {
    setPathDraft(selected?.path || '');
  }, [selected?.id, selected?.path]);

  return (
    <div className="settings-applications-section applications-page-grid">
      <PanelCard
        title="Připojené aplikace"
        subtitle="Tady spravujes napojene desktop aplikace, jejich cesty a to, co muze Luna primo otevirat."
        className="applications-panel-card"
      >
        <div className="applications-list">
          {items.length ? items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`application-card ${selected?.id === item.id ? 'is-active' : ''}`}
              onClick={() => onSelectApp(item.id)}
            >
              <div className="application-card-copy">
                <strong>{item.title}</strong>
                <p>{item.detail}</p>
              </div>
              <span className={`application-status ${item.connected ? 'is-connected' : 'is-missing'}`}>
                {item.status}
              </span>
            </button>
          )) : (
            <div className="applications-empty">
              <strong>Zatim tu nejsou zadne napojene aplikace</strong>
              <p>Jakmile Luna nacte desktop appky z backend settings, objevi se tady.</p>
            </div>
          )}
        </div>
      </PanelCard>

      <PanelCard
        title={selected?.title || 'Application Detail'}
        subtitle={selected?.connected ? 'Tahleta aplikace je pripravena pro Luna desktop akce.' : 'Tady muzes doplnit nebo upravit cestu k aplikaci.'}
        className="applications-panel-card"
      >
        {selected ? (
          <div className="application-detail-surface">
            <div className="application-detail-block">
              <span>Stav</span>
              <strong>{selected.status}</strong>
              <small>{selected.connected ? 'Luna ji umi otevrit primo z desktop shellu.' : 'Po ulozeni platne cesty se prepne do connected stavu.'}</small>
            </div>
            <div className="application-detail-block">
              <span>Cesta</span>
              <input
                className="application-path-input"
                type="text"
                value={pathDraft}
                onChange={(event) => setPathDraft(event.target.value)}
                placeholder="Zadej cestu k .exe souboru"
              />
              <small>Zadej cestu ke spustitelnému souboru aplikace.</small>
            </div>
            <div className="application-detail-actions">
              <button
                type="button"
                className="secondary-button application-save-button"
                onClick={() => onSavePath(selected, pathDraft)}
              >
                Uložit cestu
              </button>
              <button
                type="button"
                className="primary-button application-open-button"
                onClick={() => onOpenApp(selected)}
                disabled={!selected.connected}
              >
                {'Otevřít'}
              </button>
            </div>
          </div>
        ) : null}
      </PanelCard>
    </div>
  );
}

export default function SettingsPage({
  settings,
  onChange,
  onSave,
  appMeta,
  applications,
  selectedAppId,
  onSelectApp,
  onOpenApp,
  onSavePath,
}) {
  const memoryTotal = Number(appMeta.memoryGb || 0);
  const memoryBudget = memoryTotal ? Math.max(0.5, (memoryTotal * settings.memoryLimit) / 100).toFixed(1) : '--';

  return (
    <div className="section-page-grid settings-page-grid">
      <details className="advanced-settings"><summary>Pokročilé nastavení odpovědí</summary>
      <PanelCard title="Profil odpovědí" subtitle="Tyto hodnoty ovlivňují rozsah odpovědí modelu. Nerezervují paměť ani neomezují využití CPU či GPU ve Windows.">
        <div className="settings-stack">
          <div className="settings-mode-strip">
            <button type="button" className={`settings-pill ${settings.profile === 'balanced' ? 'is-active' : ''}`} onClick={() => onChange({ profile: 'balanced', cpuLimit: 55, gpuLimit: 60, memoryLimit: 50 })}>
              Balanced
            </button>
            <button type="button" className={`settings-pill ${settings.profile === 'focused' ? 'is-active' : ''}`} onClick={() => onChange({ profile: 'focused', cpuLimit: 75, gpuLimit: 85, memoryLimit: 70 })}>
              Focused
            </button>
            <button type="button" className={`settings-pill ${settings.profile === 'light' ? 'is-active' : ''}`} onClick={() => onChange({ profile: 'light', cpuLimit: 35, gpuLimit: 40, memoryLimit: 35 })}>
              Light
            </button>
          </div>

          <ResourceSlider
            label="CPU"
            value={settings.cpuLimit}
            onChange={(cpuLimit) => onChange({ cpuLimit, profile: 'custom' })}
            accentLabel="Preference výpočetního rozpočtu"
            meta={{
              primary: appMeta.cpu || 'CPU unavailable',
              secondary: `Aktualni system load: ${appMeta.cpuUsagePercent ?? '--'}%`,
            }}
          />

          <ResourceSlider
            label="GPU"
            value={settings.gpuLimit}
            onChange={(gpuLimit) => onChange({ gpuLimit, profile: 'custom' })}
            accentLabel="Preference rozpočtu modelu"
            meta={{
              primary: appMeta.gpu || 'GPU unavailable',
              secondary: `Aktualni system load: ${appMeta.gpuUsagePercent ?? '--'}%`,
            }}
          />

          <ResourceSlider
            label="Memory"
            value={settings.memoryLimit}
            onChange={(memoryLimit) => onChange({ memoryLimit, profile: 'custom' })}
            accentLabel="Preference paměťového rozpočtu"
            meta={{
              primary: memoryTotal ? `Celkem RAM: ${memoryTotal} GB` : 'RAM unavailable',
              secondary: memoryTotal ? `Orientační hodnota: ${memoryBudget} GB` : 'AI budget unavailable',
            }}
          />

          <div className="settings-actions">
            <button type="button" className="primary-button settings-save-button" onClick={onSave}>
              Uložit
            </button>
          </div>
        </div>
      </PanelCard>

      </details>

      <ApplicationsSettingsSection
        items={applications}
        selectedAppId={selectedAppId}
        onSelectApp={onSelectApp}
        onOpenApp={onOpenApp}
        onSavePath={onSavePath}
      />
    </div>
  );
}
