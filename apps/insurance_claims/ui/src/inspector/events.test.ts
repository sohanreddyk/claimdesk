import { describe, expect, it } from "vitest";
import { buildTimeline, describeEvent } from "./events";

const event = (type: string, data: Record<string, unknown> = {}, seq = 1) => ({ seq, type, data });

describe("describeEvent", () => {
  it("writes the key moments of a conversation as sentences", () => {
    const text = (e: ReturnType<typeof event>) => describeEvent(e)?.text;

    expect(text(event("IDENTITY_VERIFIED", { verified_as: "policyholder" }))).toBe(
      "Identity verified",
    );
    expect(text(event("IDENTITY_VERIFIED", { verified_as: "representative" }))).toBe(
      "Identity verified (representative)",
    );
    expect(text(event("PHASE_TRANSITION", { to: "PROCESS_CASE" }))).toBe("Moved to Process case");
    expect(text(event("PHASE_TRANSITION", { to: "COMPLETE" }))).toBe("Conversation complete");
    expect(text(event("CASE_RESOLUTION", { kind: "unique" }))).toBe("Intent resolved");
    expect(text(event("CASE_RESOLUTION", { kind: "ambiguous" }))).toBe(
      "Several claims matched; asked which one",
    );
    expect(text(event("VERIFICATION_EVALUATED", { matched_count: 2, provided_count: 3 }))).toBe(
      "Identity check: 2 of 3 details matched",
    );
    expect(text(event("PII_CAPTURED", { fields: ["full_name", "id_last4"] }))).toBe(
      "Received Full name, ID last 4",
    );
    expect(text(event("EMAIL_SENT"))).toBe("Summary email sent");
  });

  it("gives each entry an icon that matches what happened", () => {
    expect(describeEvent(event("IDENTITY_VERIFIED"))?.icon).toBe("check");
    expect(describeEvent(event("PHASE_TRANSITION", { to: "RESOLVE_INTENT" }))?.icon).toBe("arrow");
    expect(describeEvent(event("HUMAN_OFFERED"))?.icon).toBe("alert");
    expect(describeEvent(event("CONSENT_REQUESTED"))?.icon).toBe("dot");
  });

  it("says how an answer was checked", () => {
    expect(describeEvent(event("ANSWER_GENERATED", { source: "llm" }))).toMatchObject({
      text: "Answer passed the grounding guard",
      tone: "good",
    });
    expect(describeEvent(event("ANSWER_GENERATED", { source: "retry" }))?.text).toBe(
      "Answer passed the grounding guard after one retry",
    );
    expect(describeEvent(event("ANSWER_GENERATED", { source: "facts" }))?.text).toBe(
      "Answer built directly from the claim record",
    );
  });

  it("reports consent outcomes, good and bad", () => {
    expect(describeEvent(event("CONSENT_RESULT", { status: "approved" }))).toMatchObject({
      text: "Policyholder approval confirmed",
      tone: "good",
    });
    expect(describeEvent(event("CONSENT_RESULT", { status: "timed_out" }))).toMatchObject({
      text: "Policyholder approval timed out",
      tone: "warn",
    });
    expect(describeEvent(event("CONSENT_RESULT", { status: "denied" }))?.tone).toBe("warn");
  });

  it("marks problems and escalations as warnings", () => {
    for (const type of [
      "VERIFICATION_LOCKED",
      "OUTPUT_GUARD_BLOCKED",
      "LLM_FALLBACK",
      "HUMAN_OFFERED",
      "HUMAN_TRANSFER",
      "INJECTION_ATTEMPT",
      "REPRESENTATIVE_NOT_AUTHORIZED",
      "EMAIL_FAILED",
    ]) {
      expect(describeEvent(event(type))?.tone, type).toBe("warn");
    }
  });

  it("leaves out events that would only be noise", () => {
    expect(describeEvent(event("EXTRACTION_DROPPED"))).toBeNull();
    expect(describeEvent(event("PII_CAPTURED", { fields: [] }))).toBeNull();
  });

  it("falls back to a readable name for an event type it does not know", () => {
    expect(describeEvent(event("SOMETHING_NEW"))).toMatchObject({
      text: "Something new",
      tone: "neutral",
    });
  });
});

describe("buildTimeline", () => {
  it("keeps the order and the event numbers", () => {
    const items = buildTimeline([
      event("IDENTITY_VERIFIED", { verified_as: "policyholder" }, 4),
      event("PHASE_TRANSITION", { to: "RESOLVE_INTENT" }, 5),
    ]);
    expect(items.map((item) => [item.seq, item.text])).toEqual([
      [4, "Identity verified"],
      [5, "Moved to Resolve intent"],
    ]);
  });

  it("shows a claim as selected once, not on every turn", () => {
    const lookup = (seq: number, caseId: string) =>
      event("TOOL_CALL", { tool: "get_case", case_id: caseId, found: true }, seq);
    const items = buildTimeline([lookup(1, "CL-2048"), lookup(2, "CL-2048"), lookup(3, "CL-1899")]);
    expect(items.map((item) => item.text)).toEqual([
      "Claim CL-2048 selected",
      "Claim CL-1899 selected",
    ]);
    expect(items[0].icon).toBe("diamond");
  });

  it("leaves routine claim listing to the technical details", () => {
    const items = buildTimeline([event("TOOL_CALL", { tool: "list_cases", result_count: 4 })]);
    expect(items).toEqual([]);
  });

  it("flags a claim lookup that found nothing", () => {
    const items = buildTimeline([
      event("TOOL_CALL", { tool: "get_case", case_id: "CL-0000", found: false }),
    ]);
    expect(items).toEqual([
      { seq: 1, text: "Claim lookup found nothing", tone: "warn", icon: "alert" },
    ]);
  });
});
