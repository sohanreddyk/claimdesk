import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { SCENARIOS } from "./scenarios";
import { type Handler, debugView, json, mockFetch } from "./testUtils";
import type { DebugView } from "./types";

const GREETING = "Hi, I’m the claims assistant.";

/** A server that opens sessions (greetings "Greeting 2", "Greeting 3"... after the first),
 * answers chat, and serves the inspector through `debug`. */
function server({ debug, chat }: { debug: Handler; chat?: Handler }): Handler {
  let sessions = 0;
  return (url, init) => {
    if (url === "/api/session") {
      sessions += 1;
      return json({
        session_id: `s${sessions}`,
        greeting: sessions === 1 ? GREETING : `Greeting ${sessions}`,
      });
    }
    if (url.endsWith("/debug")) return debug(url, init);
    if (url === "/api/chat") return chat ? chat(url, init) : json({ reply: "ok", ended: false });
    return json({ detail: "not found" }, 404);
  };
}

/** Each call gets a fresh Response: a body can only be read once. */
const serving =
  (view?: DebugView): Handler =>
  () =>
    json(view ?? debugView());

const noInspector: Handler = () => json({ detail: "not found" }, 404);

/** The last turn of a conversation, with the given dialogue acts. */
const turn = (kinds: string[], used_llm = false): NonNullable<DebugView["last_turn"]> => ({
  acts: kinds.map((kind) => ({ kind, data: {} })),
  used_llm,
  guard_violations: [],
});

type FetchMock = ReturnType<typeof mockFetch>;
type Scope = ReturnType<typeof within>;

const callsTo = (fetchMock: FetchMock, url: string) =>
  fetchMock.mock.calls.filter(([called]) => String(called) === url);
const debugCalls = (fetchMock: FetchMock) =>
  fetchMock.mock.calls.filter(([called]) => String(called).endsWith("/debug"));
const sessionBodies = (fetchMock: FetchMock) =>
  callsTo(fetchMock, "/api/session").map(([, init]) => JSON.parse(String(init?.body)));

const messageBox = () => screen.getByLabelText("Your message");
const menuButton = () => screen.getByRole("button", { name: "Demo scenarios" });
const pane = async () =>
  within(await screen.findByRole("complementary", { name: "SOP inspector" }));

/** One named section of the inspector. */
const section = (inspector: Scope, title: string): Scope =>
  within(inspector.getByRole("region", { name: title }));
/** The label and value row for `label` inside a section. */
const rowIn = (scope: Scope, label: string) =>
  scope.getByText(label).closest(".row") as HTMLElement;

async function openWithInspector(handler: Handler) {
  const fetchMock = mockFetch(handler);
  const user = userEvent.setup();
  render(<App />);
  const inspector = await pane();
  await screen.findByText(GREETING);
  return { fetchMock, user, inspector };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("availability", () => {
  it("stays hidden, and stops asking, when the server has no inspector", async () => {
    const fetchMock = mockFetch(server({ debug: noInspector }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText(GREETING);
    await waitFor(() => expect(debugCalls(fetchMock)).toHaveLength(1));

    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.queryByText("SOP inspector")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Demo scenarios" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Workflow inspector" })).not.toBeInTheDocument();

    await user.type(messageBox(), "hello{Enter}");
    await screen.findByText("ok");
    expect(debugCalls(fetchMock)).toHaveLength(1);
  });

  it("shows the SOP inspector, marked evaluator-only, with its sections and empty states", async () => {
    const { inspector } = await openWithInspector(server({ debug: serving() }));

    expect(inspector.getByRole("heading", { name: "SOP inspector" })).toBeInTheDocument();
    expect(inspector.getByText("Evaluator only")).toBeInTheDocument();
    expect(inspector.getByText("Internal workflow state · Customer PII masked")).toBeInTheDocument();
    const titles = [
      "Workflow",
      "Identity",
      "Current case",
      "Remembered context",
      "Safety",
      "Activity",
      "Technical details",
    ];
    for (const title of titles) {
      expect(inspector.getByRole("heading", { name: title })).toBeInTheDocument();
    }
    expect(inspector.getByText("No claim selected")).toBeInTheDocument();
    expect(
      inspector.getByText("Claim details appear after verification and resolution."),
    ).toBeInTheDocument();
    expect(inspector.getByText("No intent or case hints remembered yet.")).toBeInTheDocument();
    expect(inspector.getByText("No safety issues")).toBeInTheDocument();
    expect(inspector.getByText("All SOP guards operating normally.")).toBeInTheDocument();
    expect(inspector.getByText("No activity yet")).toBeInTheDocument();
    expect(menuButton()).toBeInTheDocument();
  });

  it("ignores a debug response that is not an inspector view", async () => {
    const fetchMock = mockFetch(server({ debug: () => json({ reply: "Goodbye.", ended: true }) }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText(GREETING);
    await waitFor(() => expect(debugCalls(fetchMock)).toHaveLength(1));

    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    await user.type(messageBox(), "hello{Enter}");
    expect(await screen.findByText("ok")).toBeInTheDocument();
  });

  it("keeps the conversation and the overflow menu working when the view cannot be drawn", async () => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});
    const broken = { ...debugView(), counters: undefined } as unknown as DebugView;
    const { user, inspector } = await openWithInspector(server({ debug: serving(broken) }));

    expect(await inspector.findByText("The inspector could not be displayed.")).toBeInTheDocument();
    expect(menuButton()).toBeInTheDocument();
    await user.type(messageBox(), "hello{Enter}");
    expect(await screen.findByText("ok")).toBeInTheDocument();
    errorLog.mockRestore();
  });

  it("keeps showing the last view when a refresh fails", async () => {
    let calls = 0;
    const { inspector, user } = await openWithInspector(
      server({
        debug: () => {
          calls += 1;
          return calls === 1
            ? json(debugView({ phase: "RESOLVE_INTENT" }))
            : json({ detail: "boom" }, 500);
        },
      }),
    );
    const workflow = section(inspector, "Workflow");
    await waitFor(() => expect(rowIn(workflow, "Current step")).toHaveTextContent("Resolve intent"));

    await user.type(messageBox(), "hello{Enter}");
    await screen.findByText("ok");
    await waitFor(() => expect(calls).toBe(2));

    expect(rowIn(workflow, "Current step")).toHaveTextContent("Resolve intent");
  });

  it("stays visible after the conversation ends", async () => {
    let calls = 0;
    const { inspector, user } = await openWithInspector(
      server({
        debug: () => {
          calls += 1;
          return json(calls === 1 ? debugView() : debugView({ phase: "COMPLETE", ended: true }));
        },
        chat: () => json({ reply: "Goodbye.", ended: true }),
      }),
    );

    await user.type(messageBox(), "that's all{Enter}");

    expect(await screen.findByText("This conversation has ended.")).toBeInTheDocument();
    const workflow = section(inspector, "Workflow");
    await waitFor(() => expect(rowIn(workflow, "Current step")).toHaveTextContent("Complete"));
  });
});

describe("workflow", () => {
  it("refreshes the current step after each reply", async () => {
    let calls = 0;
    const { inspector, user } = await openWithInspector(
      server({
        debug: () => {
          calls += 1;
          return json(calls === 1 ? debugView() : debugView({ phase: "PROCESS_CASE", turns: 1 }));
        },
      }),
    );
    const workflow = section(inspector, "Workflow");
    expect(rowIn(workflow, "Current step")).toHaveTextContent("Verify identity");

    await user.type(messageBox(), "hello{Enter}");

    await waitFor(() => expect(rowIn(workflow, "Current step")).toHaveTextContent("Process case"));
    expect(rowIn(workflow, "Turns")).toHaveTextContent("1");
  });

  it("shows where the conversation is in the four phases", async () => {
    const view = debugView({ phase: "PROCESS_CASE" });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));

    const steps = within(inspector.getByRole("list", { name: "Workflow phases" }));
    const items = steps.getAllByRole("listitem");
    expect(items.map((item) => item.getAttribute("data-state"))).toEqual([
      "done",
      "done",
      "current",
      "upcoming",
    ]);
    expect(steps.getByText("Process case").closest("li")).toHaveAttribute("aria-current", "step");
    // The state is also written out for assistive technology, not only drawn.
    expect(items[0]).toHaveTextContent("(completed)");
    expect(items[2]).toHaveTextContent("(current step)");
    expect(items[3]).toHaveTextContent("(upcoming)");
  });

  it("joins the steps with a line that is filled up to the current one", async () => {
    const view = debugView({ phase: "PROCESS_CASE" });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));

    const lines = inspector.getByRole("list", { name: "Workflow phases" }).querySelectorAll(".step-line");
    expect(Array.from(lines).map((line) => line.getAttribute("data-filled"))).toEqual([
      "true",
      "true",
      "false",
    ]);
  });

  it("shows every phase as done once the conversation is complete", async () => {
    const view = debugView({ phase: "COMPLETE", ended: true });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));

    const steps = within(inspector.getByRole("list", { name: "Workflow phases" }));
    const states = steps.getAllByRole("listitem").map((item) => item.getAttribute("data-state"));
    expect(states).toEqual(["done", "done", "done", "done"]);
    expect(rowIn(section(inspector, "Workflow"), "Current step")).toHaveTextContent("Complete");
  });

  it("does not show the internal phase name in the main sections", async () => {
    const view = debugView({ phase: "PROCESS_CASE" });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));
    expect(inspector.queryByText("PROCESS_CASE")).not.toBeInTheDocument();
  });

  it("says the guard has not run before the first turn", async () => {
    const fresh = await openWithInspector(server({ debug: serving() }));
    expect(rowIn(section(fresh.inspector, "Workflow"), "Guard")).toHaveTextContent("Not run yet");
  });

  it("says there are no guard issues after a clean turn", async () => {
    const view = debugView({ turns: 1, last_turn: turn(["ASK_WHAT_NEEDED"]) });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));
    expect(rowIn(section(inspector, "Workflow"), "Guard")).toHaveTextContent("No issues");
  });

  it("counts a flagged reply", async () => {
    const flagged = debugView({
      turns: 2,
      last_turn: { acts: [], used_llm: false, guard_violations: ["leak"] },
    });
    const { inspector } = await openWithInspector(server({ debug: serving(flagged) }));
    const workflow = section(inspector, "Workflow");
    expect(rowIn(workflow, "Guard")).toHaveTextContent("1 flagged");
    expect(rowIn(workflow, "Turns")).toHaveTextContent("2");
  });
});

describe("identity", () => {
  it("starts as not verified, with a progress bar at zero and nothing else", async () => {
    const { inspector } = await openWithInspector(server({ debug: serving() }));
    const identity = section(inspector, "Identity");

    expect(identity.getByText("Not verified")).toBeInTheDocument();
    expect(rowIn(identity, "Verification")).toHaveTextContent("0 / 3 factors");
    const progress = identity.getByRole("progressbar", { name: "Verification factors matched" });
    expect(progress).toHaveAttribute("aria-valuenow", "0");
    expect(progress).toHaveAttribute("aria-valuemax", "3");
    expect(progress).toHaveAttribute("aria-valuetext", "0 of 3 factors matched");
    expect(identity.queryByText("Policy number")).not.toBeInTheDocument();
    expect(identity.queryByText("Mismatches")).not.toBeInTheDocument();
    expect(identity.queryByRole("list", { name: "Details supplied" })).not.toBeInTheDocument();
  });

  it("turns green and full when the caller is verified, with the details masked", async () => {
    const base = debugView().verification;
    const view = debugView({
      verification: {
        ...base,
        verified: true,
        verified_as: "policyholder",
        caller_role: "policyholder",
        policy_number: "POL-****",
        factors: { full_name: "M*** C***", dob: "****-**-**", id_last4: "****" },
        matched_factors: ["full_name", "dob", "id_last4"],
        mismatch_count: 1,
        refused_fields: ["phone"],
      },
      consent: { state: "approved", trail: ["pending", "approved"] },
    });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));
    const identity = section(inspector, "Identity");

    expect(identity.getByText("Verified")).toBeInTheDocument();
    expect(rowIn(identity, "Verification")).toHaveTextContent("3 / 3 factors");
    expect(identity.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "3");
    expect(rowIn(identity, "Verified as")).toHaveTextContent("Policyholder");
    expect(rowIn(identity, "Policy number")).toHaveTextContent("POL-****");
    expect(rowIn(identity, "Consent")).toHaveTextContent("Approved");
    expect(rowIn(identity, "Mismatches")).toHaveTextContent("1");
    expect(rowIn(identity, "Declined to share")).toHaveTextContent("Phone");
    const supplied = within(identity.getByRole("list", { name: "Details supplied" }));
    expect(supplied.getByText("Date of birth")).toBeInTheDocument();
    expect(supplied.getByText("****-**-**")).toBeInTheDocument();
    expect(supplied.getAllByText("Matched")).toHaveLength(3);
  });

  it("shows a representative's masked name and how they were verified", async () => {
    const base = debugView().verification;
    const view = debugView({
      verification: {
        ...base,
        verified: true,
        verified_as: "representative",
        caller_role: "representative",
        rep_name: "D*** C***",
      },
    });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));
    const identity = section(inspector, "Identity");

    expect(rowIn(identity, "Verified as")).toHaveTextContent("Representative");
    expect(identity.getByText("D*** C***")).toBeInTheDocument();
  });
});

describe("the secure-session strip", () => {
  it("states the guarantee until the inspector reports a verified caller", async () => {
    await openWithInspector(server({ debug: serving() }));
    expect(screen.getByText("Secure claims conversation")).toBeInTheDocument();
    expect(screen.queryByText("Identity verified")).not.toBeInTheDocument();
  });

  it("switches to Identity verified once the caller is verified", async () => {
    const base = debugView().verification;
    const view = debugView({ verification: { ...base, verified: true, verified_as: "policyholder" } });
    await openWithInspector(server({ debug: serving(view) }));

    expect(screen.getByText("Identity verified")).toBeInTheDocument();
    expect(screen.getByText(/Protected claim information can now be discussed/)).toBeInTheDocument();
    expect(screen.queryByText("Secure claims conversation")).not.toBeInTheDocument();
  });

  it("says so when the verified caller is a representative", async () => {
    const base = debugView().verification;
    const view = debugView({
      verification: { ...base, verified: true, verified_as: "representative" },
    });
    await openWithInspector(server({ debug: serving(view) }));
    expect(screen.getByText(/\(representative\)/)).toBeInTheDocument();
  });
});

describe("current case, remembered context and safety", () => {
  const denied = debugView({
    case: {
      resolved_case_id: "CL-2048",
      last_resolution: "unique",
      closed_cases: [],
      record: {
        case_id: "CL-2048",
        case_type: "healthcare",
        status_outcome: "denied",
        topics_discussed: ["why the claim was denied"],
        documents_needed: ["pathology report", "office note"],
        appeal_deadline: "2026-03-18",
        unavailable_documents: [],
        human_review_offered: false,
        facts_used: [],
      },
    },
  });

  it("shows the claim as a snapshot: number, status, type, deadline and documents", async () => {
    const { inspector } = await openWithInspector(server({ debug: serving(denied) }));
    const claim = section(inspector, "Current case");

    expect(claim.getByText("CL-2048")).toBeInTheDocument();
    expect(claim.getByText("Denied")).toHaveClass("chip-danger");
    expect(claim.getByText("Healthcare")).toBeInTheDocument();
    expect(rowIn(claim, "Appeal deadline")).toHaveTextContent("Mar 18, 2026");
    expect(rowIn(claim, "Documents requested")).toHaveTextContent("pathology report, office note");
    expect(claim.queryByText("No claim selected")).not.toBeInTheDocument();
  });

  it("leaves out the deadline row when the claim has no deadline", async () => {
    const closed = debugView({
      case: {
        resolved_case_id: "CL-1899",
        last_resolution: "unique",
        closed_cases: [],
        record: { ...denied.case.record, case_id: "CL-1899", case_type: "dental", status_outcome: "closed", appeal_deadline: null, documents_needed: [] },
      },
    });
    const { inspector } = await openWithInspector(server({ debug: serving(closed) }));
    const claim = section(inspector, "Current case");

    expect(claim.getByText("CL-1899")).toBeInTheDocument();
    expect(claim.getByText("Closed")).toBeInTheDocument();
    expect(claim.queryByText("Appeal deadline")).not.toBeInTheDocument();
    expect(claim.queryByText("Documents requested")).not.toBeInTheDocument();
  });

  it("lists what the agent remembered as hints, not as confirmed facts", async () => {
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
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));
    const remembered = section(inspector, "Remembered context");

    expect(remembered.getByText("Heard from the caller, not yet confirmed")).toBeInTheDocument();
    expect(rowIn(remembered, "Intent")).toHaveTextContent("Denial question");
    expect(rowIn(remembered, "Type")).toHaveTextContent("Healthcare");
    expect(rowIn(remembered, "Status")).toHaveTextContent("Denied");
    expect(rowIn(remembered, "Month")).toHaveTextContent("January 2026");
    expect(rowIn(remembered, "Claim ID")).toHaveTextContent("CL-2048");
    // A remembered "Denied" is a neutral hint tag, never a red status chip.
    expect(remembered.getByText("Denied")).toHaveClass("hint-chip");
    expect(remembered.getByText("Denied")).not.toHaveClass("chip-danger");
  });

  it("says there are no safety issues, and lists nothing that is zero", async () => {
    const { inspector } = await openWithInspector(server({ debug: serving() }));
    const safety = section(inspector, "Safety");
    expect(safety.getByText("No safety issues")).toBeInTheDocument();
    expect(safety.queryByText("Out-of-scope requests")).not.toBeInTheDocument();
  });

  it("notes signals before there is any reason to escalate", async () => {
    const base = debugView().counters;
    const view = debugView({ counters: { ...base, oos_strikes: 1, refusal_count: 2 } });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));
    const safety = section(inspector, "Safety");

    expect(safety.getByText("Signals noted")).toBeInTheDocument();
    expect(safety.getByText("No escalation yet.")).toBeInTheDocument();
    expect(rowIn(safety, "Out-of-scope requests")).toHaveTextContent("1");
    expect(rowIn(safety, "Verification refusals")).toHaveTextContent("2");
  });

  it("recommends escalation once a human has been offered", async () => {
    const base = debugView().counters;
    const view = debugView({ counters: { ...base, oos_strikes: 2, human_offered: true } });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));
    const safety = section(inspector, "Safety");

    expect(safety.getByText("Escalation recommended")).toBeInTheDocument();
    expect(rowIn(safety, "Human representative offered")).toHaveTextContent("Yes");
  });

  it("says when the caller was handed to a human", async () => {
    const base = debugView().counters;
    const view = debugView({ counters: { ...base, human_transferred: true } });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));
    expect(section(inspector, "Safety").getByText("Escalated to a human")).toBeInTheDocument();
  });

  it("counts a flagged reply as a safety signal", async () => {
    const view = debugView({
      last_turn: { acts: [], used_llm: true, guard_violations: ["leak"] },
    });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));
    const safety = section(inspector, "Safety");
    expect(safety.getByText("Signals noted")).toBeInTheDocument();
    expect(rowIn(safety, "Output guard flags")).toHaveTextContent("1");
  });
});

describe("activity", () => {
  const events = [
    { seq: 1, type: "PII_CAPTURED", data: { fields: ["full_name", "dob"] } },
    {
      seq: 2,
      type: "IDENTITY_VERIFIED",
      data: { matched_factor_count: 3, verified_as: "policyholder" },
    },
    {
      seq: 3,
      type: "PHASE_TRANSITION",
      data: { from: "VERIFY_ID", to: "RESOLVE_INTENT", reason: "identity verified" },
    },
    { seq: 4, type: "CASE_RESOLUTION", data: { kind: "unique", candidates: 1 } },
    { seq: 5, type: "TOOL_CALL", data: { tool: "list_cases", result_count: 4 } },
    { seq: 6, type: "TOOL_CALL", data: { tool: "get_case", case_id: "CL-2048", found: true } },
    { seq: 7, type: "ANSWER_GENERATED", data: { source: "llm", cited: 3, reason: null } },
  ];

  it("reads as a timeline of sentences, each with an icon and a time", async () => {
    const { inspector } = await openWithInspector(server({ debug: serving(debugView({ events })) }));
    const list = inspector.getByRole("list", { name: "Recent activity" });
    const items = within(list).getAllByRole("listitem");

    expect(items.map((item) => item.querySelector(".timeline-text")?.textContent)).toEqual([
      "Received Full name, Date of birth",
      "Identity verified",
      "Moved to Resolve intent",
      "Intent resolved",
      "Claim CL-2048 selected",
      "Answer passed the grounding guard",
    ]);
    expect(list.querySelectorAll(".timeline-icon")).toHaveLength(6);
    await waitFor(() => expect(list.querySelectorAll("time")).toHaveLength(6));
    expect(inspector.queryByText(/[{}]/)).not.toBeInTheDocument();
  });

  it("shows only the latest events and says so", async () => {
    const many = Array.from({ length: 12 }, (_, index) => ({
      seq: index + 1,
      type: "PHASE_TRANSITION",
      data: { from: "VERIFY_ID", to: "PROCESS_CASE", reason: "" },
    }));
    const { inspector } = await openWithInspector(server({ debug: serving(debugView({ events: many })) }));

    const list = inspector.getByRole("list", { name: "Recent activity" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(10);
    expect(inspector.getByText(/Showing the latest 10 of 12/)).toBeInTheDocument();
  });

  it("lists a sent email with a masked recipient, and the message only when asked", async () => {
    const view = debugView({
      outbox: [
        {
          session_id: "s1",
          to: "m***@email.com",
          subject: "Your claim summary",
          body: "Hello Margaret,\n\nClaim CL-2048",
        },
      ],
    });
    const { inspector, user } = await openWithInspector(server({ debug: serving(view) }));
    const activity = section(inspector, "Activity");

    expect(activity.getByRole("heading", { name: "Emails" })).toBeInTheDocument();
    expect(activity.getByText("m***@email.com")).toBeInTheDocument();
    expect(activity.getByText("Your claim summary")).toBeInTheDocument();
    expect(activity.queryByText(/Hello Margaret/)).not.toBeInTheDocument();

    const toggle = activity.getByRole("button", { name: "View message" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(await activity.findByText(/Hello Margaret/)).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});

describe("technical details", () => {
  const view = debugView({
    phase: "PROCESS_CASE",
    consent: { state: "approved", trail: ["pending", "approved"] },
    last_turn: {
      acts: [
        {
          kind: "ANSWER_FROM_FACTS",
          data: { source: "llm", facts_used: ["case.status", "case.denial_reason"] },
        },
        { kind: "ASK_ANYTHING_ELSE", data: {} },
      ],
      used_llm: true,
      guard_violations: [],
    },
    tool_calls: [{ seq: 3, type: "TOOL_CALL", data: { tool: "get_case", case_id: "CL-2048" } }],
    events: [{ seq: 1, type: "IDENTITY_VERIFIED", data: { matched_factor_count: 3 } }],
  });

  it("is collapsed, and keeps the low-level names out of the main sections", async () => {
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));

    const toggle = inspector.getByRole("button", { name: "Technical details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(inspector.queryByText("ANSWER_FROM_FACTS")).not.toBeInTheDocument();
    expect(inspector.queryByText("get_case")).not.toBeInTheDocument();
    expect(inspector.queryByText("PROCESS_CASE")).not.toBeInTheDocument();
  });

  it("holds the internal names, counters and trails as readable text, never JSON", async () => {
    const { inspector, user } = await openWithInspector(server({ debug: serving(view) }));

    await user.click(inspector.getByRole("button", { name: "Technical details" }));

    expect(inspector.getByText("PROCESS_CASE")).toBeInTheDocument();
    expect(inspector.getByText("ANSWER_FROM_FACTS")).toBeInTheDocument();
    expect(inspector.getByText(/source llm · facts used case.status, case.denial_reason/)).toBeInTheDocument();
    expect(inspector.getByText("get_case")).toBeInTheDocument();
    expect(inspector.getByText(/case id CL-2048/)).toBeInTheDocument();
    expect(inspector.getByText("LLM phrasing")).toBeInTheDocument();
    expect(inspector.getByText("pending → approved")).toBeInTheDocument();
    expect(inspector.getByText("Out-of-scope strikes")).toBeInTheDocument();
    expect(inspector.getByText("IDENTITY_VERIFIED")).toBeInTheDocument();
    expect(inspector.queryByText(/[{}]/)).not.toBeInTheDocument();
  });

  it("shows the audit trail as plain text, never as HTML", async () => {
    const hostile = debugView({
      events: [{ seq: 1, type: "NOTE", data: { note: "<img src=x onerror=alert(1)>" } }],
    });
    const { inspector, user } = await openWithInspector(server({ debug: serving(hostile) }));

    await user.click(inspector.getByRole("button", { name: "Technical details" }));

    expect(await inspector.findByText(/onerror=alert\(1\)/)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("the Demo scenarios menu", () => {
  it("is closed until asked for, then lists the prepared scenarios with their descriptions", async () => {
    const { user } = await openWithInspector(server({ debug: serving() }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(menuButton()).toHaveAttribute("aria-expanded", "false");

    await user.click(menuButton());

    const menu = within(screen.getByRole("menu", { name: "Demo scenarios" }));
    for (const { label, hint } of SCENARIOS) {
      expect(menu.getByRole("menuitem", { name: label })).toBeInTheDocument();
      expect(menu.getByText(hint)).toBeInTheDocument();
    }
    expect(menu.getAllByRole("menuitem")).toHaveLength(SCENARIOS.length);
    expect(menuButton()).toHaveAttribute("aria-expanded", "true");
  });

  it("is a labelled secondary button beside New conversation, not a hidden icon", async () => {
    await openWithInspector(server({ debug: serving() }));
    const trigger = menuButton();
    const header = within(trigger.closest("header") as HTMLElement);
    const newConversation = header.getByRole("button", { name: "New conversation" });

    expect(trigger).toHaveTextContent("Demo scenarios");
    expect(trigger).not.toHaveClass("btn-primary");
    // It comes before New conversation in the top-right group, and no icon-only button remains.
    expect(trigger.compareDocumentPosition(newConversation) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(screen.queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();
  });

  it("puts focus on the first item, moves with the arrow keys, and closes with Escape", async () => {
    const { user } = await openWithInspector(server({ debug: serving() }));
    await user.click(menuButton());
    const items = screen.getAllByRole("menuitem");
    expect(items[0]).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(items[1]).toHaveFocus();
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(items[items.length - 1]).toHaveFocus(); // wraps round to the last

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(menuButton()).toHaveFocus();
  });

  it("closes when the evaluator clicks elsewhere", async () => {
    const { user } = await openWithInspector(server({ debug: serving() }));
    await user.click(menuButton());
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.click(document.body);

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("starts a new conversation and fills the message box without sending it", async () => {
    const { fetchMock, user } = await openWithInspector(server({ debug: serving() }));

    await user.click(menuButton());
    await user.click(screen.getByRole("menuitem", { name: "Margaret demo" }));

    expect(await screen.findByText("Greeting 2")).toBeInTheDocument();
    await waitFor(() => expect(messageBox()).toHaveValue(SCENARIOS[0].message));
    expect(sessionBodies(fetchMock)).toEqual([{}, { consent_scenario: "default" }]);
    expect(callsTo(fetchMock, "/api/chat")).toHaveLength(0);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("starts the representative timeout scenario with the timeout consent scenario", async () => {
    const { fetchMock, user } = await openWithInspector(server({ debug: serving() }));

    await user.click(menuButton());
    await user.click(screen.getByRole("menuitem", { name: "Representative timeout" }));

    await waitFor(() =>
      expect((messageBox() as HTMLTextAreaElement).value).toContain("David Chen"),
    );
    expect(sessionBodies(fetchMock)).toEqual([{}, { consent_scenario: "timeout" }]);
  });

  it("replaces the old transcript, and the inspector follows the new session", async () => {
    const { fetchMock, user } = await openWithInspector(server({ debug: serving() }));
    await user.type(messageBox(), "hello{Enter}");
    await screen.findByText("ok");

    await user.click(menuButton());
    await user.click(screen.getByRole("menuitem", { name: "Representative approved" }));

    expect(await screen.findByText("Greeting 2")).toBeInTheDocument();
    const transcript = within(screen.getByRole("log", { name: "Conversation" }));
    expect(transcript.queryByText("hello")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(debugCalls(fetchMock).some(([url]) => String(url) === "/api/session/s2/debug")).toBe(
        true,
      ),
    );
  });

  it("is not undone by a slow reply that belonged to the old conversation", async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { user } = await openWithInspector(server({ debug: serving(), chat: () => pending }));
    await user.type(messageBox(), "hello{Enter}");
    await screen.findByText("The assistant is replying…");

    await user.click(menuButton());
    await user.click(screen.getByRole("menuitem", { name: "SSN refusal" }));
    expect(await screen.findByText("Greeting 2")).toBeInTheDocument();

    release(json({ reply: "late reply", ended: false }));
    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(screen.queryByText("late reply")).not.toBeInTheDocument();
    expect(screen.queryByText("The assistant is replying…")).not.toBeInTheDocument();
    expect(screen.getByText("Greeting 2")).toBeInTheDocument();
  });
});

describe("the Demo scenarios button", () => {
  it("is visible in evaluator mode, and clicking it opens a menu that includes Margaret demo", async () => {
    const { user } = await openWithInspector(server({ debug: serving() }));
    const trigger = screen.getByRole("button", { name: "Demo scenarios" });
    expect(trigger).toBeVisible();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(trigger);

    const menu = within(screen.getByRole("menu", { name: "Demo scenarios" }));
    expect(menu.getByRole("menuitem", { name: "Margaret demo" })).toBeInTheDocument();
    expect(menu.getByText("Happy-path denial workflow")).toBeInTheDocument();
    for (const { label } of SCENARIOS) {
      expect(menu.getByRole("menuitem", { name: label })).toBeInTheDocument();
    }
  });

  it("runs Margaret demo exactly as the scenario buttons always did", async () => {
    const { fetchMock, user } = await openWithInspector(server({ debug: serving() }));

    await user.click(screen.getByRole("button", { name: "Demo scenarios" }));
    await user.click(screen.getByRole("menuitem", { name: "Margaret demo" }));

    // A fresh conversation, with the message ready in the box and nothing sent.
    expect(await screen.findByText("Greeting 2")).toBeInTheDocument();
    await waitFor(() => expect(messageBox()).toHaveValue(SCENARIOS[0].message));
    expect(sessionBodies(fetchMock)).toEqual([{}, { consent_scenario: "default" }]);
    expect(callsTo(fetchMock, "/api/chat")).toHaveLength(0);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("can be closed again from its own button, with Escape, or by clicking elsewhere", async () => {
    const { user } = await openWithInspector(server({ debug: serving() }));
    const trigger = screen.getByRole("button", { name: "Demo scenarios" });

    await user.click(trigger);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.click(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("is not offered at all when the server has no evaluator view", async () => {
    mockFetch(server({ debug: noInspector }));
    render(<App />);
    await screen.findByText(GREETING);
    expect(screen.queryByRole("button", { name: "Demo scenarios" })).not.toBeInTheDocument();
  });
});

describe("the inspector drawer on narrower screens", () => {
  it("opens from the Workflow inspector button, moves focus in, and closes with Escape", async () => {
    const { user } = await openWithInspector(server({ debug: serving() }));
    const toggle = screen.getByRole("button", { name: "Workflow inspector" });
    const aside = screen.getByRole("complementary", { name: "SOP inspector" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(aside).not.toHaveClass("open");

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(aside).toHaveClass("open");
    expect(screen.getByRole("button", { name: "Close inspector" })).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(aside).not.toHaveClass("open");
    expect(toggle).toHaveFocus();
  });

  it("closes from its own close button or by clicking outside it", async () => {
    const { user } = await openWithInspector(server({ debug: serving() }));
    const toggle = screen.getByRole("button", { name: "Workflow inspector" });
    const aside = screen.getByRole("complementary", { name: "SOP inspector" });

    await user.click(toggle);
    await user.click(screen.getByRole("button", { name: "Close inspector" }));
    expect(aside).not.toHaveClass("open");

    await user.click(toggle);
    expect(aside).toHaveClass("open");
    await user.click(document.querySelector(".backdrop") as HTMLElement);
    expect(aside).not.toHaveClass("open");
  });
});

describe("the grounded-in-claim-record indicator", () => {
  const answered = turn(["ANSWER_FROM_FACTS", "ASK_ANYTHING_ELSE"]);

  it("marks only the answer the inspector confirms was read from the claim record", async () => {
    let calls = 0;
    const { user } = await openWithInspector(
      server({
        debug: () => {
          calls += 1;
          return json(calls === 1 ? debugView() : debugView({ last_turn: answered }));
        },
        chat: () => json({ reply: "Your claim was denied.", ended: false }),
      }),
    );
    expect(screen.queryByText("Grounded in claim record")).not.toBeInTheDocument();

    await user.type(messageBox(), "why?{Enter}");

    const mark = await screen.findByText("Grounded in claim record");
    expect(mark).toHaveAttribute("title", "Response generated from verified claim data.");
    const answer = screen.getByText("Your claim was denied.").closest("article");
    const greeting = screen.getByText(GREETING).closest("article");
    expect(answer).toContainElement(mark);
    expect(answer).toHaveClass("is-grounded");
    expect(greeting).not.toContainElement(mark);
    expect(greeting).not.toHaveClass("is-grounded");
  });

  it("does not mark a reply that was not an answer from the claim record", async () => {
    let calls = 0;
    const { user } = await openWithInspector(
      server({
        debug: () => {
          calls += 1;
          const view =
            calls === 1 ? debugView() : debugView({ last_turn: turn(["ASK_WHAT_NEEDED"]) });
          return json(view);
        },
        chat: () => json({ reply: "What would you like to know?", ended: false }),
      }),
    );

    await user.type(messageBox(), "hi{Enter}");
    await screen.findByText("What would you like to know?");
    await waitFor(() => expect(calls).toBe(2));

    expect(screen.queryByText("Grounded in claim record")).not.toBeInTheDocument();
  });

  it("stays with the reply it describes when later turns are not answers", async () => {
    let calls = 0;
    let replies = 0;
    const { user } = await openWithInspector(
      server({
        debug: () => {
          calls += 1;
          if (calls === 2) return json(debugView({ last_turn: answered }));
          if (calls === 3) return json(debugView({ last_turn: turn(["ASK_WHAT_NEEDED"]) }));
          return json(debugView());
        },
        chat: () => {
          replies += 1;
          return json({ reply: `reply ${replies}`, ended: false });
        },
      }),
    );

    await user.type(messageBox(), "one{Enter}");
    await screen.findByText("Grounded in claim record");
    await user.type(messageBox(), "two{Enter}");
    await screen.findByText("reply 2");
    await waitFor(() => expect(calls).toBe(3));

    const marks = screen.getAllByText("Grounded in claim record");
    expect(marks).toHaveLength(1);
    expect(screen.getByText("reply 1").closest("article")).toContainElement(marks[0]);
    expect(screen.getByText("reply 2").closest("article")).not.toContainElement(marks[0]);
    expect(screen.getByText("reply 2").closest("article")).not.toHaveClass("is-grounded");
  });
});
