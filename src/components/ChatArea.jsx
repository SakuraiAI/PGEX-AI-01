import lunaPortrait from '../assets/luna.jpg';
﻿import { useEffect, useRef } from 'react';
import MessageContent from './MessageContent';

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

export default function ChatArea({
  messages,
  chatId = '',
  thinkingState = null,
  pendingAction = null,
  onConfirmPendingAction = null,
  onCancelPendingAction = null,
}) {
  const displayMessages = messages;
  const hasMessages = displayMessages.length > 0;
  const messagesPanelRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (!hasMessages) return;

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
  }, [hasMessages, messages.length, chatId, thinkingState?.visible, thinkingState?.lunaActive, thinkingState?.xenoActive]);

  if (!hasMessages) {
    return (
      <section className="chat-workspace chat-workspace-empty">

        <div className="empty-chat-stage">
          <div className="empty-chat-core">
            <img className="luna-avatar" src={lunaPortrait} alt="Luna" />
          </div>
          <div className="empty-chat-copy">
            <h2>Co je dnes na programu?</h2>
            <p>Napiš zprávu nebo přilož soubor. Luna ti pomůže s dalším krokem.</p>
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
            <div className={`message-bubble ${message.role === 'user' ? 'is-user' : 'is-assistant'} ${message.author === 'Xeno' ? 'is-xeno' : ''}`}>
              <span className={`message-author ${message.author === 'Xeno' ? 'is-xeno' : ''}`}>
                {message.author || (message.role === 'user' ? 'Ty' : 'Luna')}
              </span>
              <MessageContent content={message.content} />
            </div>
          </article>
        ))}
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
