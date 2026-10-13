import lunaPortrait from '../assets/luna.jpg';
﻿import { useEffect, useRef } from 'react';
import Orb3D from './Orb3D';
import { repairDisplayedText } from '../utils/textRepair';

const markdownLinkPattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/gi;
const rawLinkPattern = /(https?:\/\/[^\s<>)]+|localhost:\d+(?:\/[^\s<>)]*)?)/gi;

function normalizeLinkHref(value) {
  const raw = String(value || '').trim();
  if (/^localhost:/i.test(raw)) {
    return `http://${raw}`;
  }
  return raw;
}

function trimLinkToken(value) {
  const token = String(value || '');
  const match = token.match(/^(.+?)([.,;:!?]+)?$/);
  if (!match) return { link: token, suffix: '' };
  return {
    link: match[1] || token,
    suffix: match[2] || '',
  };
}

function splitRawLinks(text, baseKey) {
  const parts = [];
  let cursor = 0;
  const source = String(text || '');

  for (const match of source.matchAll(rawLinkPattern)) {
    const index = match.index ?? 0;
    const fullToken = match[0] || '';
    if (index > cursor) {
      parts.push({ type: 'text', text: source.slice(cursor, index), key: `${baseKey}-text-${cursor}` });
    }

    const { link, suffix } = trimLinkToken(fullToken);
    parts.push({
      type: 'link',
      text: link,
      href: normalizeLinkHref(link),
      key: `${baseKey}-link-${index}`,
    });
    if (suffix) {
      parts.push({ type: 'text', text: suffix, key: `${baseKey}-suffix-${index}` });
    }
    cursor = index + fullToken.length;
  }

  if (cursor < source.length) {
    parts.push({ type: 'text', text: source.slice(cursor), key: `${baseKey}-text-${cursor}` });
  }

  return parts.length ? parts : [{ type: 'text', text: source, key: `${baseKey}-text-0` }];
}

function linkifyMessage(text) {
  const source = repairDisplayedText(text);
  const parts = [];
  let cursor = 0;

  for (const match of source.matchAll(markdownLinkPattern)) {
    const index = match.index ?? 0;
    const label = match[1] || match[2] || '';
    const href = match[2] || '';
    if (index > cursor) {
      parts.push(...splitRawLinks(source.slice(cursor, index), `before-${index}`));
    }
    parts.push({
      type: 'link',
      text: label,
      href,
      key: `markdown-link-${index}`,
    });
    cursor = index + (match[0] || '').length;
  }

  if (cursor < source.length) {
    parts.push(...splitRawLinks(source.slice(cursor), `after-${cursor}`));
  }

  return parts.length ? parts : [{ type: 'text', text: source, key: 'text-0' }];
}

function MessageContent({ content, trailingCaret = false }) {
  const parts = linkifyMessage(content);

  const openLink = (event, href) => {
    event.preventDefault();
    const targetUrl = normalizeLinkHref(href);
    if (window.lunaDesktop?.shell?.openExternal) {
      window.lunaDesktop.shell.openExternal(targetUrl);
      return;
    }
    window.open(targetUrl, '_blank', 'noopener,noreferrer');
  };

  return (
    <p>
      {parts.map((part) => (
        part.type === 'link' ? (
          <a
            key={part.key}
            className="message-link"
            href={normalizeLinkHref(part.href)}
            onClick={(event) => openLink(event, part.href)}
            rel="noreferrer"
          >
            {part.text}
          </a>
        ) : (
          <span key={part.key}>{part.text}</span>
        )
      ))}
      {trailingCaret ? <span className="typing-caret" /> : null}
    </p>
  );
}

function ThinkingPanel({ thinkingState }) {
  if (!thinkingState?.visible) return null;

  const lunaThinking = thinkingState?.lunaActive ?? !thinkingState?.xenoActive;
  const xenoThinking = Boolean(thinkingState?.xenoActive);
  const tracks = Array.isArray(thinkingState?.tracks) && thinkingState.tracks.length
    ? thinkingState.tracks
    : [
        ...(lunaThinking
          ? [{ speaker: 'Luna', title: 'Luna', note: 'Analyzuje zadání a skládá odpověď.' }]
          : []),
        ...(xenoThinking
          ? [{ speaker: 'Xeno', title: 'Xeno', note: 'Prochází souvislosti, rizika a hlubší návrh.' }]
          : []),
      ];

  return (
    <div className="thinking-panel" aria-live="polite">
      <div className="thinking-panel-head">
        <span className="thinking-dot" />
        <strong>Aktuální úkol</strong>
      </div>
      <div className="thinking-track-list">
        {tracks.map((track, index) => (
          <div key={`${track.speaker}-${index}`} className={`thinking-track ${track.speaker === 'Xeno' ? 'is-xeno' : ''}`}>
            <div className="thinking-track-copy">
              <span>{track.title || track.speaker}</span>
              <strong>{track.note}</strong>
            </div>
            <div className="thinking-bars" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          </div>
        ))}
      </div>
      <p>Do chatu se uloží jen finální odpověď.</p>
    </div>
  );
}

function PendingActionPanel({ pendingAction, onConfirmPendingAction, onCancelPendingAction }) {
  if (!pendingAction?.active) return null;

  return (
    <div className="pending-action-panel" aria-live="polite" aria-label={pendingAction.title || 'Luna čeká na potvrzení akce.'}>
      <p>{pendingAction.title || "Luna čeká na potvrzení akce."}</p><div className="pending-action-buttons is-centered">
        <button type="button" className="secondary-button" onClick={onCancelPendingAction}>Zrušit</button>
        <button type="button" className="primary-button" onClick={onConfirmPendingAction}>Potvrdit</button>
      </div>
    </div>
  );
}

function AgentCoreBar({ thinkingState }) {
  const lunaActive = Boolean(thinkingState?.lunaActive);
  const xenoActive = Boolean(thinkingState?.xenoActive);
  const bothActive = lunaActive && xenoActive;

  return (
    <div className={`agent-core-bar ${bothActive ? 'is-dual-active' : ''}`} aria-label="LunaAI and XenoAI status">
      <div className={`agent-core-node is-luna ${lunaActive ? 'is-active' : ''}`}>
        <span>Visible interface</span>
        <strong>LunaAI</strong>
      </div>
      <div className="agent-core-link is-left" aria-hidden="true">
        <span />
      </div>
      <div className="agent-core-orb">
        <img className="luna-avatar" src={lunaPortrait} alt="Luna" />
      </div>
      <div className="agent-core-link is-right" aria-hidden="true">
        <span />
      </div>
      <div className={`agent-core-node is-xeno ${xenoActive ? 'is-active' : ''}`}>
        <span>Reasoning layer</span>
        <strong>XenoAI</strong>
      </div>
    </div>
  );
}

function isActionLogMessage(message) {
  if (message?.role !== 'assistant') return false;
  const content = repairDisplayedText(message?.content || '').toLowerCase();
  return (
    content.includes('**akce:**')
    || content.includes('*vysledek:*')
    || content.includes('akce:')
    || content.includes('výsledek:')
    || content.includes('vysledek:')
    || content.includes('spouštím ')
    || content.includes('spoustim ')
    || content.includes('opened ')
    || content.includes('otevřela jsem ')
    || content.includes('otevrela jsem ')
  );
}

function compactActionMessages(messages) {
  const compacted = [];
  let index = 0;

  while (index < messages.length) {
    const message = messages[index];
    if (!isActionLogMessage(message)) {
      compacted.push(message);
      index += 1;
      continue;
    }

    const group = [message];
    index += 1;
    while (index < messages.length && isActionLogMessage(messages[index])) {
      group.push(messages[index]);
      index += 1;
    }

    const latest = group[group.length - 1];
    compacted.push({
      ...latest,
      id: `${latest.id || 'action'}-compact-${group.length}`,
      author: 'Agent',
      isActionLog: true,
      actionCount: group.length,
    });
  }

  return compacted;
}

export default function ChatArea({
  messages,
  chatId = '',
  thinkingState = null,
  revealingMessage = null,
  pendingAction = null,
  onConfirmPendingAction = null,
  onCancelPendingAction = null,
}) {
  const displayMessages = compactActionMessages(messages);
  const hasMessages = displayMessages.length > 0;
  const messagesPanelRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (!hasMessages && !revealingMessage?.content) return;

    const scrollToBottom = () => {
      messagesEndRef.current?.scrollIntoView({ block: 'end' });
      if (messagesPanelRef.current) {
        messagesPanelRef.current.scrollTop = messagesPanelRef.current.scrollHeight;
      }
    };

    scrollToBottom();
    const frame = window.requestAnimationFrame(scrollToBottom);
    const timeout = window.setTimeout(scrollToBottom, 80);

    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timeout);
    };
  }, [hasMessages, messages.length, chatId, thinkingState?.visible, thinkingState?.lunaActive, thinkingState?.xenoActive, revealingMessage?.content?.length]);

  if (!hasMessages && !revealingMessage?.content) {
    return (
      <section className="chat-workspace chat-workspace-empty">

        <div className="empty-chat-stage">
          <div className="empty-chat-core">
            <img className="luna-avatar" src={lunaPortrait} alt="Luna" />
          </div>
          <div className="empty-chat-copy">
            <h2>Co je dnes na programu?</h2>
            <p>Luna je pripravena naslouchat, premyslet a pomoci s dalsim krokem.</p>
          </div>
          <ThinkingPanel thinkingState={thinkingState} />
        </div>
      </section>
    );
  }

  return (
    <section className="chat-workspace is-live">

      <div className="messages-panel" ref={messagesPanelRef}>
        <ThinkingPanel thinkingState={thinkingState} />
        {displayMessages.map((message) => (
          <article key={message.id} className={`message-row ${message.role === 'user' ? 'is-user' : 'is-assistant'}`}>
            <div className={`message-bubble ${message.role === 'user' ? 'is-user' : 'is-assistant'} ${message.author === 'Xeno' ? 'is-xeno' : ''} ${message.isActionLog ? 'is-action-log' : ''}`}>
              <span className={`message-author ${message.author === 'Xeno' ? 'is-xeno' : ''} ${message.isActionLog ? 'is-action-log' : ''}`}>
                {message.author || (message.role === 'user' ? 'Ty' : 'Luna')}
                {message.isActionLog && message.actionCount > 1 ? <em>{message.actionCount} actions</em> : null}
              </span>
              <MessageContent content={message.content} />
            </div>
          </article>
        ))}
        {revealingMessage?.content ? (
          <article className="message-row is-assistant">
            <div className={`message-bubble is-assistant is-revealing ${(revealingMessage.author || 'Luna') === 'Xeno' ? 'is-xeno' : ''}`}>
              <span className={`message-author ${(revealingMessage.author || 'Luna') === 'Xeno' ? 'is-xeno' : ''}`}>{revealingMessage.author || 'Luna'}</span>
              <MessageContent content={revealingMessage.content} trailingCaret />
            </div>
          </article>
        ) : null}
        <PendingActionPanel
          pendingAction={pendingAction}
          onConfirmPendingAction={onConfirmPendingAction}
          onCancelPendingAction={onCancelPendingAction}
        />
        <div ref={messagesEndRef} />
      </div>
    </section>
  );
}
