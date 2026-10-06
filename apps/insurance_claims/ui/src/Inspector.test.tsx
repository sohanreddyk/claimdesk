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

type FetchMock = ReturnType<typeof mockFetch>;
const callsTo = (fetchMock: FetchMock, url: string) =>
  fetchMock.mock.calls.filter(([called]) => String(called) === url);
const debugCalls = (fetchMock: FetchMock) =>
  fetchMock.mock.calls.filter(([called]) => String(called).endsWith("/debug"));
const sessionBodies = (fetchMock: FetchMock) =>
  callsTo(fetchMock, "/api/session").map(([, init]) => JSON.parse(String(init?.body)));

const messageBox = () => screen.getByLabelText("Your message");
const pane = async () =>
  within(await screen.findByRole("complementary", { name: "Evaluator inspector" }));

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
    expect(screen.queryByRole("button", { name: "Margaret demo" })).not.toBeInTheDocument();

    await user.type(messageBox(), "hello{Enter}");
    await screen.findByText("ok");
    expect(debugCalls(fetchMock)).toHaveLength(1);
  });

  it("shows the inspector, the scenario buttons and an empty outbox when the server offers it", async () => {
    const { inspector } = await openWithInspector(server({ debug: serving() }));

    expect(inspector.getByText("VERIFY_ID")).toBeInTheDocument();
    expect(inspector.getByRole("heading", { name: "Verification" })).toBeInTheDocument();
    for (const { label } of SCENARIOS) {
      expect(inspector.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(inspector.getByRole("heading", { name: "Outbox (0)" })).toBeInTheDocument();
    expect(inspector.getByText("No emails sent.")).toBeInTheDocument();
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

  it("keeps the chat and the scenario buttons working when the inspector cannot be drawn", async () => {
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});
    const broken = { ...debugView(), counters: undefined } as unknown as DebugView;
    const { user, inspector } = await openWithInspector(server({ debug: serving(broken) }));

    expect(await inspector.findByText("The inspector could not be displayed.")).toBeInTheDocument();
    expect(inspector.getByRole("button", { name: "Margaret demo" })).toBeInTheDocument();
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
    expect(await inspector.findByText("RESOLVE_INTENT")).toBeInTheDocument();

    await user.type(messageBox(), "hello{Enter}");
    await screen.findByText("ok");
    await waitFor(() => expect(calls).toBe(2));

    expect(inspector.getByText("RESOLVE_INTENT")).toBeInTheDocument();
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
    expect(await inspector.findByText("COMPLETE")).toBeInTheDocument();
  });
});

describe("what it shows", () => {
  it("refreshes after each reply", async () => {
    let calls = 0;
    const { inspector, user } = await openWithInspector(
      server({
        debug: () => {
          calls += 1;
          return json(calls === 1 ? debugView() : debugView({ phase: "PROCESS_CASE", turns: 1 }));
        },
      }),
    );
    expect(inspector.getByText("VERIFY_ID")).toBeInTheDocument();

    await user.type(messageBox(), "hello{Enter}");

    expect(await inspector.findByText("PROCESS_CASE")).toBeInTheDocument();
    expect(inspector.queryByText("VERIFY_ID")).not.toBeInTheDocument();
  });

  it("lays out the workings of a verified session", async () => {
    const base = debugView();
    const view = debugView({
      phase: "PROCESS_CASE",
      turns: 2,
      verification: {
        ...base.verification,
        verified: true,
        verified_as: "policyholder",
        policy_number: "POL-****",
        factors: { dob: "****-**-**", id_last4: "****" },
        matched_factors: ["full_name", "dob", "id_last4"],
      },
      consent: { state: "approved", trail: ["pending", "approved"] },
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
      last_turn: {
        acts: [
          { kind: "ANSWER_FROM_FACTS", data: { source: "llm" } },
          { kind: "ASK_ANYTHING_ELSE", data: {} },
        ],
        used_llm: false,
        guard_violations: [],
      },
      tool_calls: [{ seq: 3, type: "TOOL_CALL", data: { tool: "get_case", case_id: "CL-2048" } }],
    });
    const { inspector } = await openWithInspector(server({ debug: serving(view) }));

    expect(inspector.getByText("PROCESS_CASE")).toBeInTheDocument();
    expect(inspector.getByText("POL-****")).toBeInTheDocument();
    expect(inspector.getByText(/\*{4}-\*{2}-\*{2}/)).toBeInTheDocument(); // masked date of birth
    expect(inspector.getByText("pending → approved")).toBeInTheDocument();
    expect(inspector.getByText("why the claim was denied")).toBeInTheDocument();
    expect(inspector.getByText("pathology report, office note")).toBeInTheDocument();
    expect(inspector.getByText("2026-03-18")).toBeInTheDocument();
    expect(inspector.getByText("ANSWER_FROM_FACTS")).toBeInTheDocument();
    expect(inspector.getByText("Fixed wording")).toBeInTheDocument();
    expect(inspector.getByText(/get_case/)).toBeInTheDocument();
  });

  it("shows the outbox with a masked recipient, and the message only when asked", async () => {
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

    expect(inspector.getByRole("heading", { name: "Outbox (1)" })).toBeInTheDocument();
    expect(inspector.getByText("m***@email.com")).toBeInTheDocument();
    expect(inspector.getByText(/Your claim summary/)).toBeInTheDocument();
    expect(inspector.queryByText(/Hello Margaret/)).not.toBeInTheDocument();

    await user.click(inspector.getByRole("button", { name: "Show message" }));
    expect(await inspector.findByText(/Hello Margaret/)).toBeInTheDocument();
    expect(inspector.getByRole("button", { name: "Hide message" })).toBeInTheDocument();
  });

  it("shows the audit trail as plain text, never as HTML", async () => {
    const view = debugView({
      events: [{ seq: 1, type: "NOTE", data: { note: "<img src=x onerror=alert(1)>" } }],
    });
    const { inspector, user } = await openWithInspector(server({ debug: serving(view) }));

    await user.click(inspector.getByRole("button", { name: "Show audit events (1)" }));

    expect(await inspector.findByText(/onerror=alert\(1\)/)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("scenario buttons", () => {
  it("start a new conversation and fill the message box without sending it", async () => {
    const { fetchMock, user, inspector } = await openWithInspector(
      server({ debug: serving() }),
    );

    await user.click(inspector.getByRole("button", { name: "Margaret demo" }));

    expect(await screen.findByText("Greeting 2")).toBeInTheDocument();
    await waitFor(() => expect(messageBox()).toHaveValue(SCENARIOS[0].message));
    expect(sessionBodies(fetchMock)).toEqual([{}, { consent_scenario: "default" }]);
    expect(callsTo(fetchMock, "/api/chat")).toHaveLength(0);
  });

  it("start the representative timeout scenario with the timeout consent scenario", async () => {
    const { fetchMock, user, inspector } = await openWithInspector(
      server({ debug: serving() }),
    );

    await user.click(inspector.getByRole("button", { name: "Representative timeout" }));

    await waitFor(() =>
      expect((messageBox() as HTMLTextAreaElement).value).toContain("David Chen"),
    );
    expect(sessionBodies(fetchMock)).toEqual([{}, { consent_scenario: "timeout" }]);
  });

  it("replace the old transcript, and the inspector follows the new session", async () => {
    const { fetchMock, user, inspector } = await openWithInspector(
      server({ debug: serving() }),
    );
    await user.type(messageBox(), "hello{Enter}");
    await screen.findByText("ok");

    await user.click(inspector.getByRole("button", { name: "Representative approved" }));

    expect(await screen.findByText("Greeting 2")).toBeInTheDocument();
    const transcript = within(screen.getByRole("log", { name: "Conversation" }));
    expect(transcript.queryByText("hello")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(debugCalls(fetchMock).some(([url]) => String(url) === "/api/session/s2/debug")).toBe(
        true,
      ),
    );
  });

  it("are not undone by a slow reply that belonged to the old conversation", async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { user, inspector } = await openWithInspector(
      server({ debug: serving(), chat: () => pending }),
    );
    await user.type(messageBox(), "hello{Enter}");
    await screen.findByText("The assistant is replying…");

    await user.click(inspector.getByRole("button", { name: "SSN refusal" }));
    expect(await screen.findByText("Greeting 2")).toBeInTheDocument();

    release(json({ reply: "late reply", ended: false }));
    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(screen.queryByText("late reply")).not.toBeInTheDocument();
    expect(screen.queryByText("The assistant is replying…")).not.toBeInTheDocument();
    expect(screen.getByText("Greeting 2")).toBeInTheDocument();
  });
});
