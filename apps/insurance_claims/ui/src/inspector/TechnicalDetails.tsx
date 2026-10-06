import { factorLabel, humanize, summarize } from "../format";
import type { DebugView } from "../types";
import { AccordionSection, Rows } from "./parts";

/** Everything an evaluator might still want, kept out of the way: the exact internal names and
 * every counter. Collapsed by default. All values are plain text and already masked. */
export function TechnicalDetails({ view }: { view: DebugView }) {
  const last = view.last_turn;
  const { verification: v, counters, consent, email } = view;

  return (
    <AccordionSection title="Technical details">
      <h4>Phase</h4>
      <Rows rows={[["Internal name", <code>{view.phase}</code>]]} />

      <h4>Last turn</h4>
      {last === null ? (
        <p className="muted">No turns yet</p>
      ) : (
        <>
          <Rows
            rows={[
              ["Reply written by", last.used_llm ? "LLM phrasing" : "Fixed wording"],
              ["Guard violations", last.guard_violations],
            ]}
          />
          <ol className="log" aria-label="Dialogue acts">
            {last.acts.map((act, index) => (
              <li key={index}>
                <code>{act.kind}</code>
                {Object.keys(act.data).length > 0 && (
                  <span className="muted"> {summarize(act.data)}</span>
                )}
              </li>
            ))}
          </ol>
        </>
      )}

      <h4>Tool calls</h4>
      {view.tool_calls.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <ul className="log" aria-label="Tool calls">
          {view.tool_calls.map((call) => {
            const { tool, ...rest } = call.data;
            return (
              <li key={call.seq}>
                <code>{String(tool ?? call.type)}</code>
                {Object.keys(rest).length > 0 && <span className="muted"> {summarize(rest)}</span>}
              </li>
            );
          })}
        </ul>
      )}

      <h4>Counters</h4>
      <Rows
        rows={[
          ["Emotion", `${counters.emotion} (severity ${counters.severity})`],
          ["Out-of-scope strikes", counters.oos_strikes],
          ["Refusals", counters.refusal_count],
          ["Frustration streak", counters.frustration_streak],
          ["Claim switches", counters.case_loops],
          ["Mismatches", v.mismatch_count],
          ["Matched factors", v.matched_factors.map(factorLabel)],
          ["Declined to share", v.refused_fields.map(factorLabel)],
          ["Human offered", counters.human_offered],
          ["Human transferred", counters.human_transferred],
        ]}
      />

      <h4>Consent and email</h4>
      <Rows
        rows={[
          ["Consent", humanize(consent.state)],
          ["Consent trail", consent.trail.length ? consent.trail.join(" → ") : null],
          ["Email", humanize(email.state)],
          ["Email address", email.address],
          ["Rejected addresses", email.rejected_alternatives],
        ]}
      />

      <h4>{`Audit events (${view.events.length})`}</h4>
      {view.events.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <ol className="log" aria-label="Audit events">
          {view.events.map((event) => (
            <li key={event.seq}>
              <code>{event.type}</code>
              {Object.keys(event.data).length > 0 && (
                <span className="muted"> {summarize(event.data)}</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </AccordionSection>
  );
}
