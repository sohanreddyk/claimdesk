// Mirrors the server's response shapes. The customer-facing responses are deliberately tiny:
// the reply text and whether the conversation has ended.

export interface SessionResponse {
  session_id: string;
  greeting: string;
}

export interface ChatResponse {
  reply: string;
  ended: boolean;
}

// The server's message cap (MAX_MESSAGE_CHARS). The server enforces it; this only stops the
// input early and drives the counter.
export const MAX_MESSAGE_CHARS = 4000;

// ---- the evaluator inspector (GET /api/session/{id}/debug) --------------------------------
// Only served when the server runs with ENABLE_DEBUG_INSPECTOR=true. Every identity value in
// it is already masked by the server.

export interface DebugAct {
  kind: string;
  data: Record<string, unknown>;
}

export interface DebugEvent {
  seq: number;
  type: string;
  data: Record<string, unknown>;
}

export interface DebugEmail {
  session_id: string;
  to: string; // masked
  subject: string;
  body: string;
}

export interface CaseRecordView {
  case_id: string | null;
  case_type: string | null;
  status_outcome: string | null;
  topics_discussed: string[];
  documents_needed: string[];
  appeal_deadline: string | null;
  unavailable_documents: string[];
  human_review_offered: boolean;
  facts_used: string[];
}

export interface DebugView {
  session_id: string;
  phase: string;
  ended: boolean;
  turns: number;
  verification: {
    verified: boolean;
    verified_as: string | null;
    caller_role: string;
    rep_name: string | null;
    factors: Record<string, string>;
    policy_number: string | null;
    matched_factors: string[];
    mismatch_count: number;
    refused_fields: string[];
  };
  consent: { state: string; trail: string[] };
  memory: { intent_hint: string | null; case_hints: Record<string, unknown> };
  case: {
    resolved_case_id: string | null;
    last_resolution: string | null;
    record: CaseRecordView;
    closed_cases: CaseRecordView[];
  };
  counters: {
    emotion: string;
    severity: number;
    refusal_count: number;
    frustration_streak: number;
    oos_strikes: number;
    case_loops: number;
    human_offered: boolean;
    human_transferred: boolean;
  };
  email: { state: string; address: string | null; rejected_alternatives: number };
  last_turn: { acts: DebugAct[]; used_llm: boolean; guard_violations: string[] } | null;
  tool_calls: DebugEvent[];
  events: DebugEvent[];
  outbox: DebugEmail[];
  history_length: number;
}
