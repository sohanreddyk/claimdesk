import type { RefObject } from "react";

/** The inspector's title, an "Evaluator only" badge and one line saying what it is. On narrower
 * screens the inspector is a drawer, and the close button here is the way out of it. */
export function InspectorHeader({
  onClose,
  closeRef,
}: {
  onClose: () => void;
  closeRef: RefObject<HTMLButtonElement | null>;
}) {
  return (
    <header className="inspector-head">
      <div className="inspector-title">
        <h2>SOP inspector</h2>
        <span className="badge">Evaluator only</span>
        <button ref={closeRef} type="button" className="btn drawer-close" onClick={onClose}>
          Close inspector
        </button>
      </div>
      <p>Internal workflow state · Customer PII masked</p>
    </header>
  );
}
