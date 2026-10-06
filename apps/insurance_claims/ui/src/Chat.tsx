import { useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import type { ChatMessage } from "./useConversation";

interface ChatProps {
  messages: ChatMessage[];
  input: string;
  onInput: (value: string) => void;
  onSend: () => void;
  onRestart: () => void;
  busy: boolean;
  starting: boolean;
  ended: boolean;
  /** A session exists, so messages can be sent. */
  ready: boolean;
  error: string | null;
  maxLength: number;
}

/** The customer-facing chat. Presentational: all state lives in useConversation. Messages are
 * rendered as plain text, never as HTML. */
export function Chat({
  messages,
  input,
  onInput,
  onSend,
  onRestart,
  busy,
  starting,
  ended,
  ready,
  error,
  maxLength,
}: ChatProps) {
  const transcriptRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const canSend = ready && !busy && !ended && !starting && input.trim().length > 0;

  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, busy]);

  // After every reply (and when the session first opens) the cursor is back in the box.
  useEffect(() => {
    if (ready && !busy && !ended && !starting) inputRef.current?.focus();
  }, [ready, busy, ended, starting]);

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSend) onSend();
    }
  }

  return (
    <section className="chat" aria-label="Claims support chat">
      <header className="chat-header">
        <h1>Claims support</h1>
      </header>

      <div
        className="transcript"
        role="log"
        aria-live="polite"
        aria-label="Conversation"
        ref={transcriptRef}
      >
        {starting && (
          <p className="status" role="status">
            Connecting…
          </p>
        )}
        {messages.map((message) => (
          <div key={message.id} className={`message ${message.role}`}>
            <span className="sr-only">{message.role === "user" ? "You: " : "Assistant: "}</span>
            {message.text}
          </div>
        ))}
        {busy && (
          <p className="status" role="status">
            The assistant is replying…
          </p>
        )}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {ended ? (
        <div className="ended">
          <p>This conversation has ended.</p>
          <button type="button" onClick={onRestart}>
            Start new conversation
          </button>
        </div>
      ) : !starting && !ready ? (
        <div className="ended">
          <button type="button" onClick={onRestart}>
            Try again
          </button>
        </div>
      ) : (
        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            if (canSend) onSend();
          }}
        >
          <label htmlFor="message" className="sr-only">
            Your message
          </label>
          <textarea
            id="message"
            ref={inputRef}
            value={input}
            maxLength={maxLength}
            rows={2}
            disabled={!ready}
            placeholder="Type your message"
            onChange={(event) => onInput(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <div className="composer-row">
            <span className="counter">
              {input.length} / {maxLength}
            </span>
            <button type="submit" disabled={!canSend}>
              Send
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
