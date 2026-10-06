/**
 * View models for the SOP inspector.
 *
 * The debug payload is shaped for the backend. These pure functions turn it into exactly what
 * each inspector section shows (human labels, ready-to-print strings, a tone for each status),
 * so the components only lay things out and the formatting rules are testable on their own.
 * Nothing here talks to the server or changes what the server sends.
 */

import {
  PHASES,
  REQUIRED_FACTORS,
  factorLabel,
  formatDate,
  humanize,
  monthName,
  phaseLabel,
} from "../format";
import type { DebugView } from "../types";
import type { StatusTone } from "./tone";

export type Pair = [label: string, value: string];

// ---- workflow -------------------------------------------------------------------------------

export type StepState = "done" | "current" | "upcoming";

export interface WorkflowViewModel {
  steps: { id: string; label: string; state: StepState }[];
  currentLabel: string;
  turns: number;
  guard: { label: string; tone: StatusTone };
}

export function toWorkflow(view: DebugView): WorkflowViewModel {
  const complete = view.phase === "COMPLETE";
  const current = PHASES.findIndex((p) => p.id === view.phase);
  const steps = PHASES.map((p, index) => {
    const state: StepState =
      complete || index < current ? "done" : index === current ? "current" : "upcoming";
    return { id: p.id, label: p.label, state };
  });

  const last = view.last_turn;
  const flagged = last?.guard_violations.length ?? 0;
  const guard: WorkflowViewModel["guard"] =
    last === null
      ? { label: "Not run yet", tone: "neutral" }
      : flagged === 0
        ? { label: "No issues", tone: "good" }
        : { label: `${flagged} flagged`, tone: "warn" };

  return { steps, currentLabel: phaseLabel(view.phase), turns: view.turns, guard };
}

// ---- identity -------------------------------------------------------------------------------

export interface IdentityViewModel {
  verified: boolean;
  status: string;
  matched: number;
  required: number;
  summary: string;
  progressLabel: string;
  details: Pair[];
  supplied: { key: string; label: string; value: string; matched: boolean }[];
}

/** Who the caller is and how far verification has got. Counters that only matter when they are
 * not zero appear only then; the rest stays under Technical details. */
export function toIdentity(view: DebugView): IdentityViewModel {
  const v = view.verification;
  const matched = Math.min(v.matched_factors.length, REQUIRED_FACTORS);
  const matchedNames = new Set(v.matched_factors);

  const details: Pair[] = [];
  if (v.verified && v.verified_as) {
    details.push(["Verified as", humanize(v.verified_as)]);
  } else if (v.caller_role && v.caller_role !== "unknown") {
    details.push(["Caller role", humanize(v.caller_role)]);
  }
  if (v.policy_number) details.push(["Policy number", v.policy_number]);
  if (v.rep_name) details.push(["Representative", v.rep_name]);
  if (view.consent.state !== "not_requested") {
    details.push(["Consent", humanize(view.consent.state)]);
  }
  if (v.mismatch_count > 0) details.push(["Mismatches", String(v.mismatch_count)]);
  if (v.refused_fields.length > 0) {
    details.push(["Declined to share", v.refused_fields.map(factorLabel).join(", ")]);
  }

  return {
    verified: v.verified,
    status: v.verified ? "Verified" : "Not verified",
    matched,
    required: REQUIRED_FACTORS,
    summary: `${matched} / ${REQUIRED_FACTORS} factors`,
    progressLabel: `${matched} of ${REQUIRED_FACTORS} factors matched`,
    details,
    supplied: Object.entries(v.factors).map(([key, value]) => ({
      key,
      label: factorLabel(key),
      value,
      matched: matchedNames.has(key),
    })),
  };
}

// ---- current case ---------------------------------------------------------------------------

export interface CaseViewModel {
  selected: boolean;
  claimId: string | null;
  caseType: string | null;
  status: { label: string; tone: StatusTone } | null;
  rows: Pair[];
}

const STATUS_TONE: Record<string, StatusTone> = {
  denied: "danger",
  open: "info",
  closed: "neutral",
};

/** The claim snapshot. The payload carries no claim date, so the appeal deadline is shown when
 * there is one, and a row with nothing to say is left out rather than shown empty. */
export function toCase(view: DebugView): CaseViewModel {
  const { resolved_case_id: claimId, record } = view.case;
  if (claimId === null) {
    return { selected: false, claimId: null, caseType: null, status: null, rows: [] };
  }
  const rows: Pair[] = [];
  if (record.appeal_deadline) rows.push(["Appeal deadline", formatDate(record.appeal_deadline)]);
  if (record.documents_needed.length > 0) {
    rows.push(["Documents requested", record.documents_needed.join(", ")]);
  }
  return {
    selected: true,
    claimId,
    caseType: record.case_type ? humanize(record.case_type) : null,
    status: record.status_outcome
      ? {
          label: humanize(record.status_outcome),
          tone: STATUS_TONE[record.status_outcome] ?? "neutral",
        }
      : null,
    rows,
  };
}

// ---- remembered context ---------------------------------------------------------------------

const KNOWN_HINTS = new Set(["case_type", "status", "month", "year", "case_id"]);
const present = (value: unknown): boolean => value !== null && value !== undefined && value !== "";

/** What the caller said, whatever phase they said it in. These are hints that were heard, not
 * confirmed claim facts, and only values that were actually heard are listed. */
export function toRemembered(view: DebugView): { rows: Pair[] } {
  const { intent_hint: intent, case_hints: hints } = view.memory;
  const rows: Pair[] = [];

  if (intent) rows.push(["Intent", humanize(intent)]);
  if (present(hints.case_type)) rows.push(["Type", humanize(String(hints.case_type))]);
  if (present(hints.status)) rows.push(["Status", humanize(String(hints.status))]);

  const month = typeof hints.month === "number" ? monthName(hints.month) : null;
  const year = present(hints.year) ? String(hints.year) : null;
  if (month) rows.push(["Month", year ? `${month} ${year}` : month]);
  else if (year) rows.push(["Year", year]);

  if (present(hints.case_id)) rows.push(["Claim ID", String(hints.case_id)]);
  for (const [key, value] of Object.entries(hints)) {
    if (!KNOWN_HINTS.has(key) && present(value)) rows.push([humanize(key), String(value)]);
  }
  return { rows };
}

// ---- safety ---------------------------------------------------------------------------------

export type SafetyLevel = "clear" | "signals" | "escalation";

export interface SafetyViewModel {
  level: SafetyLevel;
  title: string;
  detail: string;
  signals: Pair[];
}

/** The safety picture as a verdict plus only the signals that are not zero. The full set of
 * counters, zeros included, is under Technical details. */
export function toSafety(view: DebugView): SafetyViewModel {
  const counters = view.counters;
  const flagged = view.last_turn?.guard_violations.length ?? 0;

  const signals: Pair[] = [];
  if (flagged > 0) signals.push(["Output guard flags", String(flagged)]);
  if (counters.oos_strikes > 0) signals.push(["Out-of-scope requests", String(counters.oos_strikes)]);
  if (counters.refusal_count > 0) {
    signals.push(["Verification refusals", String(counters.refusal_count)]);
  }
  if (counters.frustration_streak > 0) {
    signals.push(["Frustrated turns in a row", String(counters.frustration_streak)]);
  }
  if (counters.human_offered) signals.push(["Human representative offered", "Yes"]);
  if (counters.human_transferred) signals.push(["Transferred to a human", "Yes"]);

  if (counters.human_transferred) {
    return {
      level: "escalation",
      title: "Escalated to a human",
      detail: "The caller was handed to a human representative.",
      signals,
    };
  }
  if (counters.human_offered) {
    return {
      level: "escalation",
      title: "Escalation recommended",
      detail: "A human representative has been offered.",
      signals,
    };
  }
  if (signals.length > 0) {
    return { level: "signals", title: "Signals noted", detail: "No escalation yet.", signals };
  }
  return {
    level: "clear",
    title: "No safety issues",
    detail: "All SOP guards operating normally.",
    signals,
  };
}
