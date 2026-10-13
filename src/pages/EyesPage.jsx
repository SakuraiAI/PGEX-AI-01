import PanelCard from '../sections/PanelCard';

function EyeStat({ label, value }) {
  return (
    <div className="eyes-stat-card">
      <span>{label}</span>
      <strong>{value || 'Unknown'}</strong>
    </div>
  );
}

export default function EyesPage({
  title,
  subtitle,
  observation,
  previewUrl,
  observeModeEnabled,
  busy,
  onObserveDesktop,
  onCaptureScreen,
}) {
  const screenshotPath = String(observation?.screenshot_path || '').trim();
  const screenshotUrl = String(previewUrl || '').trim();
  const activeWindow = String(observation?.active_window_title || '').trim();
  const appLabel = String(observation?.app_label || '').trim();
  const activity = String(observation?.inferred_activity || '').trim();
  const visionSummary = String(observation?.vision_summary || '').trim();
  const detail = String(observation?.detail || '').trim();
  const urlHint = String(observation?.url_hint || '').trim();

  return (
    <div className="eyes-page-grid">
      <PanelCard title={title} subtitle={subtitle} className="eyes-panel-card">
        <div className="eyes-preview-surface">
          <div className="eyes-preview-head">
            <span className={`eyes-status-pill ${observeModeEnabled ? 'is-active' : ''}`}>
              {observeModeEnabled ? 'Context armed' : 'Snapshot mode'}
            </span>
            <small>
              {busy
                ? 'Analyzing visual context...'
                : observeModeEnabled
                  ? 'Vision can reuse fresh screenshots as context.'
                  : 'Document and screenshot recognition layer'}
            </small>
          </div>

          {screenshotUrl ? (
            <div className="eyes-preview-frame">
              <img src={screenshotUrl} alt="Latest desktop capture" className="eyes-preview-image" />
            </div>
          ) : (
            <div className="eyes-preview-empty">
              <div className="eyes-preview-orb" />
              <strong>Vision is ready</strong>
              <p>Attach a document, image, or capture one screenshot. Luna and Xeno will analyze that exact file as visual context.</p>
            </div>
          )}

          <div className="eyes-stats-grid">
            <EyeStat label="App" value={appLabel} />
            <EyeStat label="Window" value={activeWindow || 'No active window yet'} />
            <EyeStat label="Activity" value={activity || 'Desktop context not captured yet'} />
            <EyeStat label="Context" value={urlHint || 'No special context detected'} />
          </div>
        </div>
      </PanelCard>

      <PanelCard
        title="Vision Control"
        subtitle="Use one-shot screenshots and attached files for grounded visual understanding. No permanent desktop stream required."
        className="eyes-panel-card"
      >
        <div className="eyes-control-surface">
          <div className="eyes-action-row">
            <button type="button" className="secondary-button" onClick={onObserveDesktop} disabled={busy}>
              Read desktop context
            </button>
            <button type="button" className="secondary-button" onClick={onCaptureScreen} disabled={busy}>
              Capture screen
            </button>
          </div>

          <div className="eyes-summary-block">
            <span>What Luna sees</span>
            <p>
              {activity || detail || 'No screenshot or visual document has been analyzed yet.'}
            </p>
          </div>

          <div className="eyes-summary-block">
            <span>Capture status</span>
            <p>{detail || 'Screenshot backend has not reported any detail yet.'}</p>
          </div>

          <div className="eyes-summary-block is-vision">
            <span>Vision summary</span>
            <p>{visionSummary || 'No screenshot, image, or document has been analyzed by the vision model yet.'}</p>
          </div>

          {screenshotPath ? (
            <div className="eyes-file-chip">
              <span>Latest capture</span>
              <strong>{screenshotPath.split(/[/\\]/).pop()}</strong>
            </div>
          ) : null}
        </div>
      </PanelCard>
    </div>
  );
}
