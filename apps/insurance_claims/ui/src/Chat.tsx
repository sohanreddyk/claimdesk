import { useEffect, useRef } from "react";
import { ConversationHeader, type SessionState } from "./conversation/ConversationHeader";
import { MessageList } from "./conversation/MessageList";
import { ConversationClosedBar, MessageComposer } from "./conversation/MessageComposer";
import { SecureSessionBanner } from "./conversation/SecureSessionBanner";
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
  /** A short, non-secret reference to the open session. */
  sessionLabel: string | null;
  /** Reply revisions the SOP inspector confirms were answered from the claim record. */
  groundedRevisions: ReadonlySet<number>;
  /** Whether the SOP inspector reports the caller as verified (false when it is not available). */
  identityVerified: boolean;
  verifiedAs: string | null;
}

/** The customer conversation: a header, the secure-session strip, the transcript and a composer.
 * Presentational: all state lives in useConversation. Messages are rendered as plain text, never
 * as HTML. */
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
  sessionLabel,
  groundedRevisions,
  identityVerified,
  verifiedAs,
}: ChatProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const canSend = ready && !busy && !ended && !starting && input.trim().length > 0;
  const state: SessionState = starting
    ? { text: "Connecting", active: false }
    : ended
      ? { text: "Session ended", active: false }
      : ready
        ? { text: "Active session", active: true }
        : { text: "Not connected", active: false };

  // After every reply (and when the session first opens) the cursor is back in the box.
  useEffect(() => {
    if (ready && !busy && !ended && !starting) inputRef.current?.focus();
  }, [ready, busy, ended, starting]);

  return (
    <section className="workspace" aria-label="Customer conversation">
      <ConversationHeader sessionLabel={sessionLabel} state={state} />
      <SecureSessionBanner verified={identityVerified} verifiedAs={verifiedAs} />
      <MessageList
        messages={messages}
        busy={busy}
        starting={starting}
        groundedRevisions={groundedRevisions}
      />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {ended || (!starting && !ready) ? (
        <ConversationClosedBar ended={ended} onRestart={onRestart} />
      ) : (
        <MessageComposer
          input={input}
          onInput={onInput}
          onSend={onSend}
          canSend={canSend}
          ready={ready}
          maxLength={maxLength}
          inputRef={inputRef}
        />
      )}
    </section>
  );
}
