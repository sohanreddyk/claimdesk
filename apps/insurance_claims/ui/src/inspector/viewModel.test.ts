import { describe, expect, it } from "vitest";
import { debugView } from "../testUtils";
import type { CaseRecordView, DebugView } from "../types";
import { toCase, toIdentity, toRemembered, toSafety, toWorkflow } from "./viewModel";

const base = debugView();
const lastTurn = (guard_violations: string[] = []) => ({
  acts: [],
  used_llm: false,
  guard_violations,
});
const withRecord = (record: Partial<CaseRecordView>, resolved = "CL-2048"): DebugView =>
  debugView({
    case: {
      resolved_case_id: resolved,
      last_resolution: "unique",
      closed_cases: [],
      record: { ...base.case.record, case_id: resolved, ...record },
    },
  });

describe("toWorkflow", () => {
  it("marks the first step current at the start, with the guard not yet run", () => {
    const flow = toWorkflow(base);
    expect(flow.steps.map((s) => s.state)).toEqual(["current", "upcoming", "upcoming", "upcoming"]);
    expect(flow.currentLabel).toBe("Verify identity");
    expect(flow.guard).toEqual({ label: "Not run yet", tone: "neutral" });
  });

  it("marks earlier steps done and later ones upcoming", () => {
    const flow = toWorkflow(debugView({ phase: "PROCESS_CASE" }));
    expect(flow.steps.map((s) => s.state)).toEqual(["done", "done", "current", "upcoming"]);
    expect(flow.currentLabel).toBe("Process case");
  });

  it("marks every step done once the conversation is complete", () => {
    const flow = toWorkflow(debugView({ phase: "COMPLETE" }));
    expect(flow.steps.every((s) => s.state === "done")).toBe(true);
    expect(flow.currentLabel).toBe("Complete");
  });

  it("describes the guard in words, never as a bare count", () => {
    expect(toWorkflow(debugView({ last_turn: lastTurn() })).guard).toEqual({
      label: "No issues",
      tone: "good",
    });
    expect(toWorkflow(debugView({ last_turn: lastTurn(["a", "b"]) })).guard).toEqual({
      label: "2 flagged",
      tone: "warn",
    });
  });
});

describe("toIdentity", () => {
  it("starts as not verified, with nothing else to say", () => {
    const identity = toIdentity(base);
    expect(identity).toMatchObject({
      verified: false,
      status: "Not verified",
      matched: 0,
      required: 3,
      summary: "0 / 3 factors",
      progressLabel: "0 of 3 factors matched",
      details: [],
      supplied: [],
    });
  });

  it("lists only the details that are present, in a fixed order", () => {
    const view = debugView({
      verification: {
        ...base.verification,
        verified: true,
        verified_as: "policyholder",
        policy_number: "POL-****",
        rep_name: null,
        matched_factors: ["full_name", "dob", "id_last4"],
        factors: { full_name: "M*** C***", dob: "****-**-**" },
        mismatch_count: 1,
        refused_fields: ["phone", "email"],
      },
      consent: { state: "approved", trail: ["pending", "approved"] },
    });
    const identity = toIdentity(view);

    expect(identity.status).toBe("Verified");
    expect(identity.matched).toBe(3);
    expect(identity.details).toEqual([
      ["Verified as", "Policyholder"],
      ["Policy number", "POL-****"],
      ["Consent", "Approved"],
      ["Mismatches", "1"],
      ["Declined to share", "Phone, Email"],
    ]);
    expect(identity.supplied).toEqual([
      { key: "full_name", label: "Full name", value: "M*** C***", matched: true },
      { key: "dob", label: "Date of birth", value: "****-**-**", matched: true },
    ]);
  });

  it("never counts more matched factors than are required", () => {
    const view = debugView({
      verification: {
        ...base.verification,
        matched_factors: ["full_name", "dob", "phone", "email", "id_last4"],
      },
    });
    expect(toIdentity(view).matched).toBe(3);
  });

  it("shows the stated role before verification and the representative's masked name", () => {
    const view = debugView({
      verification: { ...base.verification, caller_role: "representative", rep_name: "D*** C***" },
    });
    expect(toIdentity(view).details).toEqual([
      ["Caller role", "Representative"],
      ["Representative", "D*** C***"],
    ]);
  });
});

describe("toCase", () => {
  it("is empty until a claim is selected", () => {
    expect(toCase(base)).toEqual({
      selected: false,
      claimId: null,
      caseType: null,
      status: null,
      rows: [],
    });
  });

  it("shows a denied claim with a danger status, its type, deadline and documents", () => {
    const claim = toCase(
      withRecord({
        case_type: "healthcare",
        status_outcome: "denied",
        appeal_deadline: "2026-03-18",
        documents_needed: ["pathology report", "office note"],
      }),
    );
    expect(claim.claimId).toBe("CL-2048");
    expect(claim.caseType).toBe("Healthcare");
    expect(claim.status).toEqual({ label: "Denied", tone: "danger" });
    expect(claim.rows).toEqual([
      ["Appeal deadline", "Mar 18, 2026"],
      ["Documents requested", "pathology report, office note"],
    ]);
  });

  it("leaves out a row it has nothing to say for, rather than showing it empty", () => {
    const claim = toCase(
      withRecord({ case_type: "dental", status_outcome: "closed", appeal_deadline: null }),
    );
    expect(claim.rows).toEqual([]);
    expect(claim.status).toEqual({ label: "Closed", tone: "neutral" });
  });

  it("uses blue for an open claim and neutral for a status it does not know", () => {
    expect(toCase(withRecord({ status_outcome: "open" })).status?.tone).toBe("info");
    expect(toCase(withRecord({ status_outcome: "pending_review" })).status?.tone).toBe("neutral");
  });
});

describe("toRemembered", () => {
  it("has nothing when nothing was heard", () => {
    expect(toRemembered(base).rows).toEqual([]);
  });

  it("lists what was heard, in readable labels", () => {
    const view = debugView({
      memory: {
        intent_hint: "denial_question",
        case_hints: {
          case_type: "healthcare",
          status: "denied",
          month: 1,
          year: 2026,
          case_id: "CL-2048",
        },
      },
    });
    expect(toRemembered(view).rows).toEqual([
      ["Intent", "Denial question"],
      ["Type", "Healthcare"],
      ["Status", "Denied"],
      ["Month", "January 2026"],
      ["Claim ID", "CL-2048"],
    ]);
  });

  it("handles a month alone, a year alone, and a hint it does not know by name", () => {
    const month = debugView({ memory: { intent_hint: null, case_hints: { month: 3 } } });
    expect(toRemembered(month).rows).toEqual([["Month", "March"]]);

    const year = debugView({ memory: { intent_hint: null, case_hints: { year: 2025 } } });
    expect(toRemembered(year).rows).toEqual([["Year", "2025"]]);

    const other = debugView({ memory: { intent_hint: null, case_hints: { provider: "Acme" } } });
    expect(toRemembered(other).rows).toEqual([["Provider", "Acme"]]);
  });
});

describe("toSafety", () => {
  const counters = (changes: Partial<DebugView["counters"]>) => ({ ...base.counters, ...changes });

  it("says all is well, with no signals, when nothing has happened", () => {
    expect(toSafety(base)).toEqual({
      level: "clear",
      title: "No safety issues",
      detail: "All SOP guards operating normally.",
      signals: [],
    });
  });

  it("notes signals, listing only the ones that are not zero", () => {
    const safety = toSafety(debugView({ counters: counters({ oos_strikes: 1, refusal_count: 2 }) }));
    expect(safety.level).toBe("signals");
    expect(safety.title).toBe("Signals noted");
    expect(safety.signals).toEqual([
      ["Out-of-scope requests", "1"],
      ["Verification refusals", "2"],
    ]);
  });

  it("counts a flagged reply as a signal", () => {
    const safety = toSafety(debugView({ last_turn: lastTurn(["leak"]) }));
    expect(safety.level).toBe("signals");
    expect(safety.signals).toEqual([["Output guard flags", "1"]]);
  });

  it("recommends escalation once a human has been offered", () => {
    const safety = toSafety(debugView({ counters: counters({ human_offered: true }) }));
    expect(safety.level).toBe("escalation");
    expect(safety.title).toBe("Escalation recommended");
  });

  it("says when the caller was handed to a human", () => {
    const safety = toSafety(debugView({ counters: counters({ human_transferred: true }) }));
    expect(safety.level).toBe("escalation");
    expect(safety.title).toBe("Escalated to a human");
  });
});
