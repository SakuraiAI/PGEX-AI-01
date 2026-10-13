import { useEffect, useRef, useState } from 'react';
import { normalizeTransportText } from '../utils/textRepair';

export default function ChatInput({
  value,
  onChange,
  onSend,
  onAction,
  attachment,
  onClearAttachment,
  centered = false,
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const fileInputRef = useRef(null);
  const menuRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    if (!menuOpen) return undefined;

    function handlePointerDown(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    }

    window.addEventListener('pointerdown', handlePointerDown);
    return () => window.removeEventListener('pointerdown', handlePointerDown);
  }, [menuOpen]);

  useEffect(() => {
    if (!textareaRef.current) return;
    textareaRef.current.style.height = '0px';
    const nextHeight = Math.max(30, Math.min(textareaRef.current.scrollHeight, 144));
    textareaRef.current.style.height = `${nextHeight}px`;
  }, [value, attachment?.name, centered]);

  function handleFileChange(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    onAction('file', file);
    setMenuOpen(false);
    event.target.value = '';
  }

  function handleTextChange(event) {
    onChange(normalizeTransportText(event.target.value));
  }

  function handlePaste(event) {
    const pastedText = event.clipboardData?.getData('text');
    if (!pastedText) return;

    const repairedText = normalizeTransportText(pastedText);
    if (repairedText === pastedText) return;

    event.preventDefault();
    const target = event.currentTarget;
    const selectionStart = target.selectionStart ?? value.length;
    const selectionEnd = target.selectionEnd ?? selectionStart;
    const nextValue = `${value.slice(0, selectionStart)}${repairedText}${value.slice(selectionEnd)}`;
    onChange(nextValue);

    window.requestAnimationFrame(() => {
      const caret = selectionStart + repairedText.length;
      target.selectionStart = caret;
      target.selectionEnd = caret;
    });
  }

  function handleKeyDown(event) {
    if (event.isComposing) return;
    if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey) {
      event.preventDefault();
      onSend();
    }
  }

  const isImageAttachment = Boolean(attachment?.previewUrl && attachment?.type?.startsWith('image/'));

  return (
    <div className={`chat-input-shell ${centered ? 'is-centered' : ''}`}>
      <div className="chat-input-plus-zone" ref={menuRef}>
        <button
          className={`input-icon-button ${menuOpen ? 'is-open' : ''}`}
          type="button"
          onClick={() => setMenuOpen((current) => !current)}
          aria-label="Přidat přílohu nebo akci"
          aria-expanded={menuOpen}
        >
          +
        </button>
        {menuOpen && (
          <div className="chat-plus-menu">
            <button type="button" onClick={() => fileInputRef.current?.click()}>Přiložit soubor</button>
            <button type="button" onClick={() => { onAction('screenshot'); setMenuOpen(false); }}>
              Snímek obrazovky
            </button>
          </div>
        )}
        <input ref={fileInputRef} type="file" hidden onChange={handleFileChange} />
      </div>

      <div className="chat-input-main">
        {attachment && (
          <div className={`attachment-chip ${isImageAttachment ? 'is-image' : ''}`}>
            {isImageAttachment && <img src={attachment.previewUrl} alt={attachment.name} className="attachment-preview" />}
            <span>{attachment.name}</span>
            <button type="button" onClick={onClearAttachment} aria-label="Odebrat přílohu">x</button>
          </div>
        )}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleTextChange}
          onPaste={handlePaste}
          onKeyDown={handleKeyDown}
          placeholder="Napiš Luně…"
          aria-label="Zpráva pro Lunu"
          rows={1}
        />
      </div>
      <button className="send-button" type="button" onClick={() => onSend()}>Odeslat</button>
    </div>
  );
}
