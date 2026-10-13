import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { repairDisplayedText } from '../utils/textRepair';

const plugins = [remarkGfm];

function CopyButton({ text, label = 'Kopírovat' }) {
  const [state, setState] = useState('');
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState('Zkopírováno');
    } catch {
      setState('Kopírování se nezdařilo');
    }
  }
  return <span className="copy-control"><button type="button" onClick={copy}>{label}</button><span role="status">{state}</span></span>;
}

function ExternalLink({ href, children }) {
  const safeHref = /^https?:\/\//i.test(href || '') ? href : undefined;
  const [failed, setFailed] = useState(false);
  if (!safeHref) return <span>{children}</span>;
  async function open(event) {
    event.preventDefault();
    try {
      if (window.lunaDesktop?.shell?.openExternal) await window.lunaDesktop.shell.openExternal(safeHref);
      else window.open(safeHref, '_blank', 'noopener,noreferrer');
    } catch {
      setFailed(true);
    }
  }
  return <><a href={safeHref} onClick={open} rel="noreferrer">{children}</a>{failed && <small role="alert">Odkaz se nepodařilo otevřít.</small>}</>;
}

function CodeBlock({ children }) {
  const code = String(children?.props?.children || '');
  return <div className="message-code"><CopyButton text={code} label="Kopírovat kód" /><pre>{children}</pre></div>;
}

const components = {
  a: ExternalLink,
  pre: CodeBlock,
  // Remote images should not load automatically when the model supplies a URL.
  img: ({ alt }) => <span>[Obrázek: {alt || 'bez popisu'}]</span>,
};

export default function MessageContent({ content }) {
  const text = repairDisplayedText(content || '');
  return <div className="message-content">
    <ReactMarkdown remarkPlugins={plugins} components={components} skipHtml>{text}</ReactMarkdown>
    <CopyButton text={text} label="Kopírovat zprávu" />
  </div>;
}
