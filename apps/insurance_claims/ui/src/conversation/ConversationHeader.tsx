import { useEffect, useState } from "react";
import { CopyIcon } from "../icons";

export interface SessionState {
  text: string;
  active: boolean;
}

/** The conversation's title, a quiet session reference with a copy button, and its state. The
 * reference is short and not secret; the full session id is never shown or copied. */
export function ConversationHeader({
  sessionLabel,
  state,
}: {
  sessionLabel: string | null;
  state: SessionState;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copy() {
    if (!sessionLabel) return;
    try {
      await navigator.clipboard.writeText(sessionLabel);
      setCopied(true);
    } catch {
      // Copying is a convenience; if the browser refuses, nothing else is affected.
    }
  }

  return (
    <header className="conv-head">
      <div className="conv-head-main">
        <h1>Customer conversation</h1>
        <p className="meta">
          {sessionLabel ? (
            <>
              <span>Session {sessionLabel}</span>
              <button
                type="button"
                className="icon-btn icon-btn-small"
                aria-label="Copy session reference"
                onClick={() => void copy()}
              >
                <CopyIcon size={12} />
              </button>
              {copied && <span role="status">Copied</span>}
            </>
          ) : (
            <span>No active session</span>
          )}
        </p>
      </div>
      <span className={state.active ? "state state-active" : "state"}>
        <span className="state-dot" aria-hidden="true" />
        {state.text}
      </span>
    </header>
  );
}
