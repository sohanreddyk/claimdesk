import { useId, useState } from "react";
import type { ReactNode } from "react";
import type { CaseRecordView, DebugView } from "./types";

/** A value as the evaluator reads it: plain text, never HTML. */
function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="inspector-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function Rows({ rows }: { rows: [label: string, value: unknown][] }) {
  return (
    <dl className="rows">
      {rows.map(([label, value]) => (
        <div key={label} className="row">
          <dt>{label}</dt>
          <dd>{show(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Collapsible({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div>
      <button
        type="button"
        className="link"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? "Hide" : "Show"} {title}
      </button>
      {open && <div id={id}>{children}</div>}
    </div>
  );
}

function recordRows(record: CaseRecordView): [string, unknown][] {
  return [
    ["Claim type", record.case_type],
    ["Outcome", record.status_outcome],
    ["Topics discussed", record.topics_discussed],
    ["Documents needed", record.documents_needed],
    ["Appeal deadline", record.appeal_deadline],
    ["Unavailable documents", record.unavailable_documents],
    ["Human review offered", record.human_review_offered],
  ];
}

/** The evaluator's view of what the agent is doing. Every identity value arrives already
 * masked from the server; this component only lays it out. */
export function Inspector({ view }: { view: DebugView | null }) {
  if (!view) {
    return (
      <p className="status" role="status">
        Waiting for a session…
      </p>
    );
  }

  const { verification, consent, memory, counters, email } = view;
  const factors = Object.entries(verification.factors);

  return (
    <div className="inspector-body">
      <Section title="Overview">
        <dl className="rows">
          <div className="row">
            <dt>Phase</dt>
            <dd>
              <span className="badge">{view.phase}</span>
            </dd>
          </div>
        </dl>
        <Rows
          rows={[
            ["Ended", view.ended],
            ["Turns", view.turns],
          ]}
        />
      </Section>

      <Section title="Verification">
        <Rows
          rows={[
            ["Verified", verification.verified],
            ["Verified as", verification.verified_as],
            ["Caller role", verification.caller_role],
            ["Representative", verification.rep_name],
            ["Policy number", verification.policy_number],
            ["Matched factors", verification.matched_factors],
            ["Mismatches", verification.mismatch_count],
            ["Refused fields", verification.refused_fields],
          ]}
        />
        {factors.length > 0 && (
          <ul className="plain">
            {factors.map(([name, value]) => (
              <li key={name}>
                <code>{name}</code>: {value}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Consent">
        <Rows
          rows={[
            ["State", consent.state],
            ["Trail", consent.trail.length ? consent.trail.join(" → ") : null],
          ]}
        />
      </Section>

      <Section title="Memory">
        <Rows
          rows={[
            ["Remembered request", memory.intent_hint],
            ["Claim hints", Object.keys(memory.case_hints).length ? memory.case_hints : null],
          ]}
        />
      </Section>

      <Section title="Claim">
        <Rows
          rows={[
            ["Resolved claim", view.case.resolved_case_id],
            ["Resolution", view.case.last_resolution],
            ...recordRows(view.case.record),
            ["Earlier claims", view.case.closed_cases.map((c) => c.case_id)],
          ]}
        />
      </Section>

      <Section title="Counters">
        <Rows
          rows={[
            ["Emotion", counters.emotion],
            ["Severity", counters.severity],
            ["Frustration streak", counters.frustration_streak],
            ["Refusals", counters.refusal_count],
            ["Out-of-scope strikes", counters.oos_strikes],
            ["Claim switches", counters.case_loops],
            ["Human offered", counters.human_offered],
            ["Human transferred", counters.human_transferred],
          ]}
        />
      </Section>

      <Section title="Email">
        <Rows
          rows={[
            ["State", email.state],
            ["Address", email.address],
            ["Rejected alternatives", email.rejected_alternatives],
          ]}
        />
      </Section>

      <Section title="Last turn">
        {view.last_turn === null ? (
          <p className="muted">No turns yet.</p>
        ) : (
          <>
            <Rows
              rows={[
                ["Reply written by", view.last_turn.used_llm ? "LLM phrasing" : "Fixed wording"],
                ["Guard violations", view.last_turn.guard_violations],
              ]}
            />
            <ol className="plain">
              {view.last_turn.acts.map((act, index) => (
                <li key={index}>
                  <code>{act.kind}</code>{" "}
                  {Object.keys(act.data).length > 0 && (
                    <span className="muted">{JSON.stringify(act.data)}</span>
                  )}
                </li>
              ))}
            </ol>
          </>
        )}
      </Section>

      <Section title="Tool calls">
        {view.tool_calls.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <ul className="plain">
            {view.tool_calls.map((call) => (
              <li key={call.seq}>
                #{call.seq} <span className="muted">{JSON.stringify(call.data)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`Outbox (${view.outbox.length})`}>
        {view.outbox.length === 0 ? (
          <p className="muted">No emails sent.</p>
        ) : (
          <ul className="plain">
            {view.outbox.map((mail, index) => (
              <li key={index}>
                <div>
                  To: <code>{mail.to}</code>
                </div>
                <div>Subject: {mail.subject}</div>
                <Collapsible title="message">
                  <pre className="body">{mail.body}</pre>
                </Collapsible>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Audit trail">
        <Collapsible title={`audit events (${view.events.length})`}>
          <ol className="plain">
            {view.events.map((event) => (
              <li key={event.seq}>
                #{event.seq} <code>{event.type}</code>{" "}
                {Object.keys(event.data).length > 0 && (
                  <span className="muted">{JSON.stringify(event.data)}</span>
                )}
              </li>
            ))}
          </ol>
        </Collapsible>
      </Section>
    </div>
  );
}
