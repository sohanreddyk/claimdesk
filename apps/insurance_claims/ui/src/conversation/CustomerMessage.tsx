import { formatTime } from "../format";
import type { ChatMessage } from "../useConversation";

/** The customer's message: right-aligned, compact, solid brand blue. Plain text only. */
export function CustomerMessage({ message }: { message: ChatMessage }) {
  return (
    <article className="msg msg-customer" aria-label="Message from you">
      <header className="msg-meta">
        <span className="sender">You</span>
        <span aria-hidden="true">·</span>
        <time dateTime={new Date(message.at).toISOString()}>{formatTime(message.at)}</time>
      </header>
      <p className="msg-body">{message.text}</p>
    </article>
  );
}
