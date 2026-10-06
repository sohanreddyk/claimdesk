import { factorLabel, humanize, phaseLabel } from "../format";
import type { DebugEvent } from "../types";
import type { StatusTone } from "./tone";

export type Tone = StatusTone;
export type TimelineIcon = "check" | "arrow" | "diamond" | "alert" | "dot";

export interface Described {
  text: string;
  tone: Tone;
  icon: TimelineIcon;
}

export interface TimelineItem extends Described {
  seq: number;
}

const str = (value: unknown): string => (typeof value === "string" ? value : "");
const num = (value: unknown): number => (typeof value === "number" ? value : 0);
const entry = (text: string, tone: Tone, icon: TimelineIcon): Described => ({ text, tone, icon });

/** One audit event as a short sentence an evaluator can read at a glance. Null for events that
 * are only noise in a timeline (they remain in the technical details). */
export function describeEvent(event: DebugEvent): Described | null {
  const d = event.data;
  switch (event.type) {
    case "IDENTITY_VERIFIED":
      return entry(
        d.verified_as === "representative"
          ? "Identity verified (representative)"
          : "Identity verified",
        "good",
        "check",
      );
    case "VERIFICATION_EVALUATED":
      return entry(
        `Identity check: ${num(d.matched_count)} of ${num(d.provided_count)} details matched`,
        "neutral",
        "dot",
      );
    case "VERIFICATION_LOCKED":
      return entry("Verification locked after repeated mismatches", "warn", "alert");
    case "PII_CAPTURED": {
      const fields = Array.isArray(d.fields) ? d.fields.map((f) => factorLabel(String(f))) : [];
      return fields.length ? entry(`Received ${fields.join(", ")}`, "neutral", "dot") : null;
    }
    case "CASE_HINT_CAPTURED":
      return entry("Claim details remembered", "neutral", "dot");
    case "PHASE_TRANSITION": {
      const to = str(d.to);
      return entry(
        to === "COMPLETE" ? "Conversation complete" : `Moved to ${phaseLabel(to)}`,
        "neutral",
        "arrow",
      );
    }
    case "CASE_RESOLUTION":
      switch (str(d.kind)) {
        case "unique":
          return entry("Intent resolved", "neutral", "arrow");
        case "ambiguous":
          return entry("Several claims matched; asked which one", "neutral", "arrow");
        case "no_match":
          return entry("No claim matched the description", "neutral", "arrow");
        case "no_claims":
          return entry("No claims on file", "neutral", "arrow");
        default:
          return entry(humanize(str(d.kind) || "case resolution"), "neutral", "arrow");
      }
    case "CLAIM_SWITCH":
      return entry("Caller asked about another claim", "neutral", "arrow");
    case "ANSWER_GENERATED":
      if (d.source === "llm") return entry("Answer passed the grounding guard", "good", "check");
      if (d.source === "retry") {
        return entry("Answer passed the grounding guard after one retry", "good", "check");
      }
      return entry("Answer built directly from the claim record", "good", "check");
    case "OUTPUT_GUARD_BLOCKED":
      return entry("Output guard replaced a reply", "warn", "alert");
    case "LLM_FALLBACK":
      return entry("Language model unavailable; used built-in wording", "warn", "alert");
    case "CONSENT_REQUESTED":
      return entry("Policyholder approval requested", "neutral", "dot");
    case "CONSENT_RESULT":
      switch (str(d.status)) {
        case "approved":
          return entry("Policyholder approval confirmed", "good", "check");
        case "timed_out":
          return entry("Policyholder approval timed out", "warn", "alert");
        case "denied":
          return entry("Policyholder declined approval", "warn", "alert");
        default:
          return entry("Policyholder approval checked", "neutral", "dot");
      }
    case "REPRESENTATIVE_DETECTED":
      return entry("Caller identified as a representative", "neutral", "dot");
    case "REPRESENTATIVE_NOT_AUTHORIZED":
      return entry("Representative is not authorized", "warn", "alert");
    case "HUMAN_OFFERED":
      return entry("Human representative offered", "warn", "alert");
    case "HUMAN_TRANSFER":
      return entry("Transferred to a human representative", "warn", "alert");
    case "INJECTION_ATTEMPT":
      return entry("Attempt to change the agent's instructions declined", "warn", "alert");
    case "UNSUPPORTED_ACTION":
      return entry("Unsupported request declined", "neutral", "dot");
    case "EMAIL_SENT":
      return entry("Summary email sent", "good", "check");
    case "EMAIL_FAILED":
      return entry("Summary email could not be sent", "warn", "alert");
    case "EXTRACTION_DROPPED":
      return null;
    default:
      return entry(humanize(event.type.toLowerCase()), "neutral", "dot");
  }
}

/** The audit trail as a readable timeline. Looking a claim up is shown once, as "selected", when
 * the claim changes, not on every turn; listing claims is routine and left to the details. */
export function buildTimeline(events: readonly DebugEvent[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  let lastClaim: string | null = null;
  for (const event of events) {
    if (event.type === "TOOL_CALL") {
      if (event.data.tool !== "get_case") continue;
      if (event.data.found !== true) {
        items.push({ seq: event.seq, ...entry("Claim lookup found nothing", "warn", "alert") });
        continue;
      }
      const id = str(event.data.case_id);
      if (id && id !== lastClaim) {
        lastClaim = id;
        items.push({ seq: event.seq, ...entry(`Claim ${id} selected`, "neutral", "diamond") });
      }
      continue;
    }
    const described = describeEvent(event);
    if (described) items.push({ seq: event.seq, ...described });
  }
  return items;
}
