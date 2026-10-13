import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/theme.css';
import './styles/workspace.css';

class RootErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ error, info });
    console.error('LunaAI renderer crashed', error, info);
  }

  render() {
    if (!this.state.error) {
      return this.props.children;
    }

    const message = String(this.state.error?.message || this.state.error || 'Unknown renderer error');
    const stack = String(this.state.error?.stack || this.state.info?.componentStack || '').trim();

    return (
      <div
        style={{
          minHeight: '100vh',
          background: '#050505',
          color: '#f5f5f5',
          padding: '32px',
          fontFamily: '"Segoe UI", sans-serif',
        }}
      >
        <div
          style={{
            maxWidth: '980px',
            margin: '0 auto',
            padding: '28px',
            border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: '24px',
            background: 'rgba(16,16,16,0.96)',
            boxShadow: '0 24px 80px rgba(0,0,0,0.45)',
          }}
        >
          <h1 style={{ margin: '0 0 12px', fontSize: '28px' }}>LunaAI renderer error</h1>
          <p style={{ margin: '0 0 18px', color: 'rgba(255,255,255,0.72)' }}>
            The Electron window loaded, but the React renderer crashed during startup.
          </p>
          <pre
            style={{
              margin: 0,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              padding: '18px',
              borderRadius: '18px',
              background: '#0b0b0b',
              border: '1px solid rgba(255,255,255,0.08)',
              color: '#f5f5f5',
              fontFamily: 'Consolas, "Courier New", monospace',
              fontSize: '13px',
              lineHeight: 1.5,
            }}
          >
            {message}
            {stack ? `\n\n${stack}` : ''}
          </pre>
        </div>
      </div>
    );
  }
}

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('Missing #root element in renderer HTML.');
}

window.addEventListener('error', (event) => {
  console.error('Unhandled window error', event.error || event.message || event);
});

window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled promise rejection', event.reason || event);
});

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </React.StrictMode>,
);
