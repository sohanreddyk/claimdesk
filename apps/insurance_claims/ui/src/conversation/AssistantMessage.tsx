import { formatTime } from "../format";
import { ShieldCheckIcon } from "../icons";
import type { ChatMessage } from "../useConversation";
import { GroundedBadge } from "./GroundedBadge";

/** One support entry. An ordinary reply (verification prompts, clarifications, anything not read
 * from a claim) is a quiet bordered card. A claim answer the inspector confirms is grounded gets
 * the blue accent and the grounded badge, so the answers that matter stand out. */
export function AssistantMessage({
  message,
  grounded,
}: {
  message: ChatMessage;
  grounded: boolean;
}) {
  return (
    <article
      className={grounded ? "msg msg-assistant is-grounded" : "msg msg-assistant"}
      aria-label="Message from Claims support"
    >
      <span className="avatar" aria-hidden="true">
        <ShieldCheckIcon size={14} strokeWidth={1.8} />
      </span>
      <div className="msg-main">
        <header className="msg-meta">
          <span className="sender">Claims support</span>
          <span className="sender-tag">Automated</span>
          <span aria-hidden="true">·</span>
          <time dateTime={new Date(message.at).toISOString()}>{formatTime(message.at)}</time>
        </header>
        <div className="msg-card">
          <p className="msg-body">{message.text}</p>
          {grounded && <GroundedBadge />}
        </div>
      </div>
    </article>
  );
}
