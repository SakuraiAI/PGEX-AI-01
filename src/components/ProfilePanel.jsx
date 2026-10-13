function UsageMeter({ value }) {
  const safeValue = typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : null;
  return (
    <div className="usage-meter">
      <div className="usage-meter-fill" style={{ width: `${safeValue ?? 0}%` }} />
    </div>
  );
}

function UsageValue({ value }) {
  return <strong className="usage-value">{typeof value === 'number' ? `${value}%` : '--'}</strong>;
}

export default function ProfilePanel({ visible, appMeta, onClose }) {
  if (!visible) return null;
  return (
    <aside className={`profile-panel ${visible ? 'is-open' : ''}`}>
      <div className="profile-panel-card">
        <div className="profile-panel-head">
          <div className="profile-panel-avatar">L</div>
          <div>
            <h3>O zařízení</h3>
            <p>LunaAI</p>
          </div>
        </div>

        <div className="profile-detail-block">
          <span>Zařízení</span>
          <strong>{appMeta.deviceName || 'Unknown device'}</strong>
          <small>{appMeta.os || 'Windows'} · {appMeta.arch || 'x64'}</small>
        </div>

        <div className="profile-detail-grid">
          <div>
            <span>CPU</span>
            <UsageValue value={appMeta.cpuUsagePercent} />
            <small>{appMeta.cpu || 'Unavailable'}</small>
            <UsageMeter value={appMeta.cpuUsagePercent} />
          </div>
          <div>
            <span>GPU</span>
            <UsageValue value={appMeta.gpuUsagePercent} />
            <small>{appMeta.gpu || 'Unavailable'}{appMeta.gpuVendor && appMeta.gpuVendor !== 'unknown' ? ` · ${appMeta.gpuVendor.toUpperCase()}` : ''}</small>
            <UsageMeter value={appMeta.gpuUsagePercent} />
          </div>
          <div>
            <span>Paměť</span>
            <UsageValue value={appMeta.memoryUsagePercent} />
            <small>{appMeta.memoryGb ? `${appMeta.memoryUsedGb || 0} / ${appMeta.memoryGb} GB` : 'Unknown'}</small>
            <UsageMeter value={appMeta.memoryUsagePercent} />
          </div>
          <div>
            <span>Verze</span>
            <strong>{appMeta.version || '0.1.0'}</strong>
            <small>{appMeta.platform || 'desktop'}</small>
          </div>
        </div>

        <div className="profile-panel-actions">
          <button className="secondary-button" type="button" onClick={onClose}>Zavřít</button>
        </div>
      </div>
    </aside>
  );
}
