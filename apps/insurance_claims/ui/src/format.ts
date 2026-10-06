import type { DebugView } from "./types";

/** The four SOP phases, in order, with the labels the evaluator reads. */
export const PHASES = [
  { id: "VERIFY_ID", label: "Verify identity" },
  { id: "RESOLVE_INTENT", label: "Resolve intent" },
  { id: "PROCESS_CASE", label: "Process case" },
  { id: "POST_PROCESS", label: "Follow-up" },
] as const;

/** Matching factors needed to verify. The server never accepts fewer than three. */
export const REQUIRED_FACTORS = 3;

const FACTOR_LABELS: Record<string, string> = {
  full_name: "Full name",
  dob: "Date of birth",
  phone: "Phone",
  email: "Email",
  id_last4: "ID last 4",
};

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** A short clock time for a transcript entry, in the viewer's locale. */
export function formatTime(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** "Today" for a moment on the current calendar day, otherwise a short date ("Mar 2"). */
export function dayLabel(ms: number, now: number = Date.now()): string {
  const day = new Date(ms);
  if (day.toDateString() === new Date(now).toDateString()) return "Today";
  return day.toLocaleDateString([], { month: "short", day: "numeric" });
}

/** "hint_case_type" -> "Case type", "denial_question" -> "Denial question". */
export function humanize(key: string): string {
  const spaced = key.replace(/^hint_/, "").replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function factorLabel(name: string): string {
  return FACTOR_LABELS[name] ?? humanize(name);
}

/** "PROCESS_CASE" -> "Process case", "COMPLETE" -> "Complete". */
export function phaseLabel(phase: string): string {
  if (phase === "COMPLETE") return "Complete";
  return PHASES.find((p) => p.id === phase)?.label ?? humanize(phase.toLowerCase());
}

/** 1 -> "January". Null for anything that is not a month number. */
export function monthName(month: number): string | null {
  return MONTHS[month - 1] ?? null;
}

/** "2026-03-18" -> "Mar 18, 2026". Computed from the text, so it never shifts with the viewer's
 * time zone or locale. Anything that is not a plain ISO date is returned as it came. */
export function formatDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${month.slice(0, 3)} ${Number(match[3])}, ${match[1]}` : iso;
}

/** A value as the evaluator reads it: plain text, never HTML. */
export function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return `${Object.keys(value).length} fields`;
  return String(value);
}

function brief(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.map(brief).join(", ") : "—";
  if (typeof value === "object") return `${Object.keys(value).length} fields`;
  const text = String(value);
  return text.length > 80 ? `${text.slice(0, 77)}…` : text;
}

/** Structured data as one short readable line ("source llm · facts used a, b"), never JSON. */
export function summarize(data: Record<string, unknown>): string {
  return Object.entries(data)
    .map(([key, value]) => `${key.replace(/_/g, " ")} ${brief(value)}`)
    .join(" · ");
}

/** True when the last turn answered a claim question from the claim record and no output check
 * flagged the reply. Both the model's answers (which passed the grounding guard) and the
 * facts-only fallback (grounded by construction) come out as this one act. */
export function hasGroundedAnswer(view: DebugView): boolean {
  const turn = view.last_turn;
  if (turn === null) return false;
  return (
    turn.guard_violations.length === 0 && turn.acts.some((act) => act.kind === "ANSWER_FROM_FACTS")
  );
}
