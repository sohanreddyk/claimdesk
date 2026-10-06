import { useEffect } from "react";
import type { KeyboardEvent, RefObject } from "react";
import { ArrowRightIcon } from "../icons";

/** The composer: one elevated container holding the text box and its footer. Enter sends and
 * Shift+Enter starts a new line. The box grows with what is typed, up to a limit set in CSS. */
export function MessageComposer({
  input,
  onInput,
  onSend,
  canSend,
  ready,
  maxLength,
  inputRef,
}: {
  input: string;
  onInput: (value: string) => void;
  onSend: () => void;
  canSend: boolean;
  ready: boolean;
  maxLength: number;
  inputRef: RefObject<HTMLTextAreaElement | null>;
}) {
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    if (el.scrollHeight > 0) el.style.height = `${el.scrollHeight}px`;
  }, [input, inputRef]);

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSend) onSend();
    }
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSend) onSend();
      }}
    >
      <div className="composer-inner">
        <div className="composer-box">
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
          <div className="composer-bar">
            <span className="counter">
              {input.length} / {maxLength}
            </span>
            <span className="composer-hint">Enter to send · Shift+Enter for new line</span>
            <button type="submit" className="btn btn-primary btn-send" disabled={!canSend}>
              Send
              <ArrowRightIcon size={14} strokeWidth={2} />
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}

/** Where the composer would be once the conversation is over, or could not start. */
export function ConversationClosedBar({
  ended,
  onRestart,
}: {
  ended: boolean;
  onRestart: () => void;
}) {
  return (
    <div className="composer">
      <div className="composer-inner closed-bar">
        {ended && <p>This conversation has ended.</p>}
        <button type="button" className="btn btn-primary" onClick={onRestart}>
          {ended ? "Start new conversation" : "Try again"}
        </button>
      </div>
    </div>
  );
}
