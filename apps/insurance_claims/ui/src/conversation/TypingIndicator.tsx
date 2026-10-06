/** Three quiet dots while a reply is on its way. The reply is not streamed, so this only says
 * "working"; the words are there for screen readers. */
export function TypingIndicator() {
  return (
    <div className="typing" role="status">
      <span className="typing-dots" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span className="sr-only">The assistant is replying…</span>
    </div>
  );
}
