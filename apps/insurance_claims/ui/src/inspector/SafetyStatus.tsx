import { AlertIcon, ShieldCheckIcon } from "../icons";
import type { DebugView } from "../types";
import { Rows, Section } from "./parts";
import { toSafety } from "./viewModel";

/** The safety verdict as a clear status card, with only the signals that are not zero below it.
 * The state is written in words and shown with an icon, not left to colour alone. */
export function SafetyStatus({ view }: { view: DebugView }) {
  const safety = toSafety(view);

  return (
    <Section title="Safety">
      <div className={`safety-card safety-${safety.level}`}>
        <span className="safety-icon" aria-hidden="true">
          {safety.level === "clear" ? <ShieldCheckIcon size={18} /> : <AlertIcon size={18} />}
        </span>
        <div>
          <p className="safety-title">{safety.title}</p>
          <p className="safety-detail">{safety.detail}</p>
        </div>
      </div>
      {safety.signals.length > 0 && <Rows rows={safety.signals} />}
    </Section>
  );
}
