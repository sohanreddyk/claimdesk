import { describe, expect, it } from "vitest";
import {
  dayLabel,
  factorLabel,
  formatDate,
  hasGroundedAnswer,
  humanize,
  monthName,
  phaseLabel,
  show,
  summarize,
} from "./format";
import { debugView } from "./testUtils";

describe("humanize", () => {
  it("turns stored keys into readable labels", () => {
    expect(humanize("hint_case_type")).toBe("Case type");
    expect(humanize("denial_question")).toBe("Denial question");
    expect(humanize("month")).toBe("Month");
  });
});

describe("show", () => {
  it("writes values as plain text", () => {
    expect(show(null)).toBe("—");
    expect(show("")).toBe("—");
    expect(show(0)).toBe("0");
    expect(show(true)).toBe("yes");
    expect(show(false)).toBe("no");
    expect(show([])).toBe("—");
    expect(show(["a", "b"])).toBe("a, b");
  });
});

describe("summarize", () => {
  it("writes structured data as one readable line, never as JSON", () => {
    const text = summarize({
      source: "llm",
      facts_used: ["case.status", "case.denial_reason"],
      nested: { a: 1, b: 2 },
      empty: [],
      none: null,
    });
    expect(text).toBe(
      "source llm · facts used case.status, case.denial_reason · nested 2 fields · empty — · none —",
    );
    expect(text).not.toMatch(/[{}[\]"]/);
  });

  it("shortens a very long value", () => {
    expect(summarize({ note: "x".repeat(200) })).toBe(`note ${"x".repeat(77)}…`);
  });

  it("has nothing to say about no data", () => {
    expect(summarize({})).toBe("");
  });
});

describe("hasGroundedAnswer", () => {
  const turn = (kinds: string[], guard_violations: string[] = []) => ({
    acts: kinds.map((kind) => ({ kind, data: {} })),
    used_llm: false,
    guard_violations,
  });

  it("is true when the last turn answered from the claim record", () => {
    const view = debugView({ last_turn: turn(["ANSWER_FROM_FACTS", "ASK_ANYTHING_ELSE"]) });
    expect(hasGroundedAnswer(view)).toBe(true);
  });

  it("is false when there was no answer, no turn, or a flagged reply", () => {
    expect(hasGroundedAnswer(debugView())).toBe(false);
    expect(hasGroundedAnswer(debugView({ last_turn: turn(["ASK_WHAT_NEEDED"]) }))).toBe(false);
    const flagged = debugView({ last_turn: turn(["ANSWER_FROM_FACTS"], ["leak"]) });
    expect(hasGroundedAnswer(flagged)).toBe(false);
  });
});

describe("phaseLabel", () => {
  it("names each phase for people, and the finished state", () => {
    expect(phaseLabel("VERIFY_ID")).toBe("Verify identity");
    expect(phaseLabel("RESOLVE_INTENT")).toBe("Resolve intent");
    expect(phaseLabel("PROCESS_CASE")).toBe("Process case");
    expect(phaseLabel("POST_PROCESS")).toBe("Follow-up");
    expect(phaseLabel("COMPLETE")).toBe("Complete");
  });

  it("still reads sensibly for a phase it does not know", () => {
    expect(phaseLabel("SOMETHING_ELSE")).toBe("Something else");
  });
});

describe("monthName", () => {
  it("turns a month number into its name", () => {
    expect(monthName(1)).toBe("January");
    expect(monthName(12)).toBe("December");
  });

  it("has no name for anything else", () => {
    expect(monthName(0)).toBeNull();
    expect(monthName(13)).toBeNull();
  });
});

describe("dayLabel", () => {
  const now = new Date(2026, 2, 5, 12, 30).getTime();

  it("calls a moment on the current day Today", () => {
    expect(dayLabel(new Date(2026, 2, 5, 9, 0).getTime(), now)).toBe("Today");
    expect(dayLabel(now, now)).toBe("Today");
  });

  it("gives any other day a short date instead", () => {
    const label = dayLabel(new Date(2026, 2, 2, 9, 0).getTime(), now);
    expect(label).not.toBe("Today");
    expect(label).toMatch(/2/);
  });
});

describe("formatDate", () => {
  it("writes an ISO date the way a person would, without depending on the time zone", () => {
    expect(formatDate("2026-03-18")).toBe("Mar 18, 2026");
    expect(formatDate("2026-01-05")).toBe("Jan 5, 2026");
    expect(formatDate("2025-12-31")).toBe("Dec 31, 2025");
  });

  it("returns anything that is not a plain ISO date unchanged", () => {
    expect(formatDate("next Tuesday")).toBe("next Tuesday");
    expect(formatDate("2026-13-01")).toBe("2026-13-01");
    expect(formatDate("")).toBe("");
  });
});

describe("factorLabel", () => {
  it("names the identity factors for people", () => {
    expect(factorLabel("dob")).toBe("Date of birth");
    expect(factorLabel("id_last4")).toBe("ID last 4");
    expect(factorLabel("some_new_factor")).toBe("Some new factor");
  });
});
