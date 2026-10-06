import { useEffect, useRef } from "react";
import { dayLabel, formatTime } from "../format";
import type { ChatMessage } from "../useConversation";
import { AssistantMessage } from "./AssistantMessage";
import { CustomerMessage } from "./CustomerMessage";
import { TypingIndicator } from "./TypingIndicator";

/** The transcript: a scrolling canvas with a centered reading column. Entries begin at the top,
 * a small time marker is shown once above the first message of the session, and the view follows
 * the newest entry (smoothly, unless the viewer prefers reduced motion). */
export function MessageList({
  messages,
  busy,
  starting,
  groundedRevisions,
}: {
  messages: ChatMessage[];
  busy: boolean;
  starting: boolean;
  groundedRevisions: ReadonlySet<number>;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const previousCount = useRef(0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    // The first message of a session appears in place; later ones are followed smoothly.
    const smooth = !reduced && previousCount.current > 0;
    previousCount.current = messages.length;
    if (typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, busy]);

  const first = messages[0];

  return (
    <div className="transcript" ref={scrollRef}>
      <div className="transcript-inner" role="log" aria-live="polite" aria-label="Conversation">
        {starting && (
          <p className="system-note" role="status">
            Connecting…
          </p>
        )}
        {first && (
          <p className="time-divider">
            {dayLabel(first.at)} · {formatTime(first.at)}
          </p>
        )}
        {messages.map((message) =>
          message.role === "user" ? (
            <CustomerMessage key={message.id} message={message} />
          ) : (
            <AssistantMessage
              key={message.id}
              message={message}
              grounded={message.revision !== null && groundedRevisions.has(message.revision)}
            />
          ),
        )}
        {busy && <TypingIndicator />}
      </div>
    </div>
  );
}
