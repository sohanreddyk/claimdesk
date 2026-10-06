import type { DebugView } from "../types";
import { Rows, Section } from "./parts";
import { toRemembered } from "./viewModel";

/** What the caller said, whatever phase they said it in. These are hints that were heard, not
 * confirmed claim facts, so they are drawn as neutral, dashed-outline tags and never in a
 * status colour. */
export function RememberedContext({ view }: { view: DebugView }) {
  const { rows } = toRemembered(view);

  return (
    <Section title="Remembered context" subtitle="Heard from the caller, not yet confirmed">
      {rows.length === 0 ? (
        <p className="muted">No intent or case hints remembered yet.</p>
      ) : (
        <Rows
          rows={rows.map(([label, value]): [string, unknown] => [
            label,
            <span className="hint-chip">{value}</span>,
          ])}
        />
      )}
    </Section>
  );
}
