import { vi } from "vitest";
import type { CaseRecordView, DebugView } from "./types";

export type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Replaces fetch with a function that answers through `handler`. */
export function mockFetch(handler: Handler) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(handler(String(input), init)),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

const emptyRecord: CaseRecordView = {
  case_id: null,
  case_type: null,
  status_outcome: null,
  topics_discussed: [],
  documents_needed: [],
  appeal_deadline: null,
  unavailable_documents: [],
  human_review_offered: false,
  facts_used: [],
};

/** A realistic inspector payload for a brand-new session, with any part overridden. */
export function debugView(overrides: Partial<DebugView> = {}): DebugView {
  return {
    session_id: "s1",
    phase: "VERIFY_ID",
    ended: false,
    turns: 0,
    verification: {
      verified: false,
      verified_as: null,
      caller_role: "unknown",
      rep_name: null,
      factors: {},
      policy_number: null,
      matched_factors: [],
      mismatch_count: 0,
      refused_fields: [],
    },
    consent: { state: "not_requested", trail: [] },
    memory: { intent_hint: null, case_hints: {} },
    case: { resolved_case_id: null, last_resolution: null, record: emptyRecord, closed_cases: [] },
    counters: {
      emotion: "neutral",
      severity: 0,
      refusal_count: 0,
      frustration_streak: 0,
      oos_strikes: 0,
      case_loops: 0,
      human_offered: false,
      human_transferred: false,
    },
    email: { state: "not_offered", address: null, rejected_alternatives: 0 },
    last_turn: null,
    tool_calls: [],
    events: [],
    outbox: [],
    history_length: 1,
    ...overrides,
  };
}
