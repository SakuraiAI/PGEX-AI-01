import { useState } from 'react';
import PanelCard from '../sections/PanelCard';

const profiles = [
  { id: 'light', label: 'Úsporný', value: 35, detail: 'Menší rozpočet odpovědi a jeden pracovní krok.' },
  { id: 'balanced', label: 'Běžný', value: 50, detail: 'Vyvážený rozpočet odpovědi a až dva pracovní kroky.' },
  { id: 'focused', label: 'Podrobný', value: 70, detail: 'Větší rozpočet odpovědi a až tři pracovní kroky.' },
];

export default function SettingsPage({ settings, onChange, onSave, applications = [], applicationsError = '', onRefreshApps, onOpenApp }) {
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null);
  const [query, setQuery] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [opening, setOpening] = useState('');
  const [appResult, setAppResult] = useState(null);
  const budget = Math.min(settings.cpuLimit, settings.gpuLimit, settings.memoryLimit);
  const profile = budget <= 35 ? 'light' : budget <= 50 ? 'balanced' : 'focused';
  const matching = applications.filter(item => item.title.toLocaleLowerCase('cs').includes(query.toLocaleLowerCase('cs').trim()));

  async function save() {
    setSaving(true);
    try { setSaveResult(await onSave()); }
    catch { setSaveResult({ ok: false, message: 'Nastavení se nepodařilo uložit. Zkus to znovu.' }); }
    finally { setSaving(false); }
  }
  async function refresh() {
    setRefreshing(true);
    try { await onRefreshApps(); }
    finally { setRefreshing(false); }
  }
  async function open(item) {
    setOpening(item.key); setAppResult(null);
    try { setAppResult(await onOpenApp(item)); }
    catch { setAppResult({ ok: false, message: 'Aplikaci se nepodařilo spustit.' }); }
    finally { setOpening(''); }
  }

  return <div className="section-page-grid settings-page-grid">
    <details className="advanced-settings"><summary>Pokročilé nastavení odpovědí</summary>
      <PanelCard title="Profil odpovědí" subtitle="Profil mění rozpočet odpovědi a rozsah práce asistenta. Vyšší rozpočet může znamenat delší čekání. Výkon CPU, GPU ani RAM počítače neomezuje.">
        <div className="settings-stack">
          <div className="settings-mode-strip">
            {profiles.map(item => <button key={item.id} type="button" disabled={saving} aria-pressed={profile === item.id} className={`settings-pill ${profile === item.id ? 'is-active' : ''}`} onClick={() => {
              onChange({ profile: item.id, cpuLimit: item.value, gpuLimit: item.value, memoryLimit: item.value });
              setSaveResult({ ok: true, message: 'Změna ještě není uložená.' });
            }}>{item.label}</button>)}
          </div>
          <p>{profiles.find(item => item.id === profile)?.detail}</p>
          <p>Projeví se od další odeslané zprávy po uložení. Neurčuje přesný počet slov.</p>
          <button type="button" className="primary-button settings-save-button" disabled={saving} onClick={save}>{saving ? 'Ukládám…' : 'Uložit profil'}</button>
          {saveResult && <p role={saveResult.ok ? 'status' : 'alert'}>{saveResult.message}</p>}
        </div>
      </PanelCard>
    </details>
    <PanelCard title="Aplikace v počítači" subtitle="PGEX načítá aplikace z nabídky Start ve Windows. Cesty vyplňovat nemusíš. V chatu můžeš napsat například „Otevři Blender“.">
      <div className="installed-app-toolbar">
        <input className="sidebar-search" aria-label="Hledat aplikaci" placeholder="Hledat aplikaci…" value={query} onChange={event => setQuery(event.target.value)} />
        <button type="button" className="secondary-button" disabled={refreshing} onClick={refresh}>{refreshing ? 'Hledám…' : 'Obnovit seznam'}</button>
      </div>
      {applicationsError && <p role="alert">{applicationsError}</p>}
      {appResult && <p role={appResult.ok ? 'status' : 'alert'}>{appResult.message}</p>}
      <div className="installed-app-list">
        {matching.map(item => <div className="installed-app-row" key={item.key}>
          <span>{item.title}</span>
          <button type="button" className="secondary-button" disabled={Boolean(opening)} onClick={() => open(item)} aria-label={`Otevřít ${item.title}`}>{opening === item.key ? 'Spouštím…' : 'Otevřít'}</button>
        </div>)}
        {!matching.length && <p>{applications.length ? 'Žádná aplikace neodpovídá hledání.' : 'Seznam se připravuje. Pokud zůstane prázdný, zkus jej obnovit.'}</p>}
      </div>
    </PanelCard>
  </div>;
}
