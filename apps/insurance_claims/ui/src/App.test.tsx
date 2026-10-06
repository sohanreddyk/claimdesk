import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { type Handler, json, mockFetch } from "./testUtils";

const GREETING = "Hi, I’m the insurance claims support assistant. Please share your full name.";

type User = ReturnType<typeof userEvent.setup>;

/** A server that opens sessions normally and answers chat with `chat` (default: a plain "ok"). */
function api(chat?: Handler): Handler {
  return (url, init) => {
    if (url === "/api/session") return json({ session_id: "s1", greeting: GREETING });
    if (url === "/api/chat") return chat ? chat(url, init) : json({ reply: "ok", ended: false });
    return json({ detail: "not found" }, 404);
  };
}

const box = () => screen.getByLabelText("Your message");
const sendButton = () => screen.getByRole("button", { name: "Send" });
const transcript = () => within(screen.getByRole("log", { name: "Conversation" }));

function chatCalls(fetchMock: ReturnType<typeof mockFetch>) {
  return fetchMock.mock.calls.filter(([url]) => String(url) === "/api/chat");
}

async function open(): Promise<User> {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText(GREETING);
  return user;
}

async function say(user: User, text: string) {
  await user.type(box(), text);
  await user.click(sendButton());
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("starting a conversation", () => {
  it("shows the greeting from the server once the session opens", async () => {
    mockFetch(api());
    render(<App />);
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
    expect(await screen.findByText(GREETING)).toBeInTheDocument();
    expect(screen.queryByText("Connecting…")).not.toBeInTheDocument();
    expect(screen.getByRole("log", { name: "Conversation" })).toBeInTheDocument();
  });

  it("creates exactly one session even under React StrictMode", async () => {
    const fetchMock = mockFetch(api());
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    await screen.findByText(GREETING);
    const sessionCalls = fetchMock.mock.calls.filter(([url]) => String(url) === "/api/session");
    expect(sessionCalls).toHaveLength(1);
  });

  it("offers a retry when the session cannot be created", async () => {
    let attempts = 0;
    mockFetch((url) => {
      if (url !== "/api/session") return json({}, 404);
      attempts += 1;
      return attempts === 1
        ? json({ detail: "too many active sessions" }, 503)
        : json({ session_id: "s1", greeting: GREETING });
    });
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The service is busy. Please try again in a moment.",
    );
    expect(screen.queryByText("too many active sessions")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(GREETING)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("sending messages", () => {
  it("sends the message with the session id and shows the reply", async () => {
    const fetchMock = mockFetch(api(() => json({ reply: "Your claim was denied.", ended: false })));
    const user = await open();

    await say(user, "Why was it denied?");

    expect(await screen.findByText("Your claim was denied.")).toBeInTheDocument();
    expect(transcript().getByText("Why was it denied?")).toBeInTheDocument();
    const [call] = chatCalls(fetchMock);
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      session_id: "s1",
      message: "Why was it denied?",
    });
    expect(box()).toHaveValue("");
  });

  it("does not allow sending while a reply is in flight", async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetchMock = mockFetch(api(() => pending));
    const user = await open();

    await say(user, "hello");
    expect(await screen.findByText("The assistant is replying…")).toBeInTheDocument();
    expect(sendButton()).toBeDisabled();

    await user.type(box(), "more{Enter}"); // typing is fine, sending is not
    expect(sendButton()).toBeDisabled();
    expect(chatCalls(fetchMock)).toHaveLength(1);

    release(json({ reply: "hi there", ended: false }));
    expect(await screen.findByText("hi there")).toBeInTheDocument();
    await waitFor(() => expect(sendButton()).toBeEnabled());
    expect(screen.queryByText("The assistant is replying…")).not.toBeInTheDocument();
    await waitFor(() => expect(box()).toHaveFocus());
  });

  it("cannot send an empty or whitespace-only message", async () => {
    const fetchMock = mockFetch(api());
    const user = await open();

    expect(sendButton()).toBeDisabled();
    await user.type(box(), "   {Enter}");
    expect(sendButton()).toBeDisabled();
    expect(chatCalls(fetchMock)).toHaveLength(0);
  });

  it("sends on Enter, and Shift+Enter adds a new line instead", async () => {
    const fetchMock = mockFetch(api());
    const user = await open();

    await user.type(box(), "first{Shift>}{Enter}{/Shift}second");
    expect(box()).toHaveValue("first\nsecond");
    expect(chatCalls(fetchMock)).toHaveLength(0);

    await user.type(box(), "{Enter}");
    expect(await screen.findByText("ok")).toBeInTheDocument();
    expect(chatCalls(fetchMock)).toHaveLength(1);
  });

  it("limits the message length and shows a live counter", async () => {
    mockFetch(api());
    const user = await open();

    expect(box()).toHaveAttribute("maxlength", "4000");
    expect(screen.getByText("0 / 4000")).toBeInTheDocument();
    await user.type(box(), "abc");
    expect(screen.getByText("3 / 4000")).toBeInTheDocument();
  });

  it("shows replies as plain text, never as HTML", async () => {
    const hostile = "<img src=x onerror=alert(1)> **bold** <b>not bold</b>";
    mockFetch(api(() => json({ reply: hostile, ended: false })));
    const user = await open();

    await say(user, "hello");

    expect(await screen.findByText(hostile)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
  });
});

describe("when the conversation ends", () => {
  it("locks the input and offers a fresh conversation", async () => {
    let sessions = 0;
    mockFetch((url) => {
      if (url === "/api/session") {
        sessions += 1;
        return json({
          session_id: `s${sessions}`,
          greeting: sessions === 1 ? GREETING : "A fresh start.",
        });
      }
      if (url === "/api/chat") return json({ reply: "Goodbye.", ended: true });
      return json({ detail: "not found" }, 404);
    });
    const user = await open();

    await say(user, "that's all");
    expect(await screen.findByText("Goodbye.")).toBeInTheDocument();
    expect(screen.getByText("This conversation has ended.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Your message")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Start new conversation" }));

    expect(await screen.findByText("A fresh start.")).toBeInTheDocument();
    expect(screen.queryByText("Goodbye.")).not.toBeInTheDocument();
    expect(screen.queryByText("that's all")).not.toBeInTheDocument();
    expect(box()).toBeEnabled();
    expect(sessions).toBe(2);
  });
});

describe("failures", () => {
  it("explains an expired session in plain words and locks the conversation", async () => {
    mockFetch(api(() => json({ detail: "session not found" }, 404)));
    const user = await open();

    await say(user, "hello");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This session has expired. Please start a new conversation.",
    );
    expect(screen.queryByText("session not found")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Your message")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start new conversation" })).toBeInTheDocument();
  });

  it("shows a generic error for a server failure and gives the message back", async () => {
    mockFetch(api(() => json({ detail: "internal error" }, 500)));
    const user = await open();

    await say(user, "hello");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong. Please try again.",
    );
    expect(screen.queryByText("internal error")).not.toBeInTheDocument();
    expect(transcript().queryByText("hello")).not.toBeInTheDocument();
    expect(box()).toHaveValue("hello");
    await waitFor(() => expect(sendButton()).toBeEnabled());
  });

  it("reports an unreachable server, and clears the error on the next send", async () => {
    let up = false;
    mockFetch(
      api(() => {
        if (!up) throw new TypeError("Failed to fetch");
        return json({ reply: "back again", ended: false });
      }),
    );
    const user = await open();

    await say(user, "hello");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server.");

    up = true;
    await user.click(sendButton());
    expect(await screen.findByText("back again")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("the console", () => {
  it("labels every entry with its sender and a time", async () => {
    mockFetch(api(() => json({ reply: "Your claim was denied.", ended: false })));
    const user = await open();
    await say(user, "Why was it denied?");
    await screen.findByText("Your claim was denied.");

    const entries = within(screen.getByRole("log", { name: "Conversation" })).getAllByRole("article");
    expect(entries.map((entry) => entry.getAttribute("aria-label"))).toEqual([
      "Message from Claims support",
      "Message from you",
      "Message from Claims support",
    ]);
    for (const entry of entries) {
      const time = entry.querySelector("time");
      expect(time?.getAttribute("datetime")).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    }
    // The agent's entries say they are automated; the customer's do not.
    expect(within(entries[0]).getByText("Claims support")).toBeInTheDocument();
    expect(within(entries[0]).getByText("Automated")).toBeInTheDocument();
    expect(within(entries[1]).getByText("You")).toBeInTheDocument();
    expect(within(entries[1]).queryByText("Automated")).not.toBeInTheDocument();
  });

  it("shows the session and whether the conversation is open or ended", async () => {
    mockFetch(api(() => json({ reply: "Goodbye.", ended: true })));
    const user = await open();
    expect(screen.getByText("Active session")).toBeInTheDocument();
    expect(screen.getByText(/^Session /)).toBeInTheDocument();

    await say(user, "that's all");

    expect(await screen.findByText("Session ended")).toBeInTheDocument();
    expect(screen.queryByText("Active session")).not.toBeInTheDocument();
  });

  it("copies a short session reference, never the full session id", async () => {
    mockFetch(api());
    const user = await open();

    await user.click(screen.getByRole("button", { name: "Copy session reference" }));

    expect(await screen.findByText("Copied")).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe("s1");
  });

  it("has a clean header: the product name, its tagline, a synthetic-data badge and New conversation", async () => {
    mockFetch(api());
    await open();

    const header = within(screen.getByText("ClaimDesk").closest("header") as HTMLElement);
    expect(header.getByText("ClaimDesk")).toBeInTheDocument();
    expect(header.getByText("Guided insurance claims support")).toBeInTheDocument();
    expect(header.getByText("Demo · synthetic data")).toBeInTheDocument();
    expect(header.getByRole("button", { name: "New conversation" })).toBeInTheDocument();
  });

  it("opens with a secure-session strip that states the guarantee", async () => {
    mockFetch(api());
    await open();

    expect(screen.getByText("Secure claims conversation")).toBeInTheDocument();
    expect(
      screen.getByText(/Identity verification is required before protected claim information/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Identity verified")).not.toBeInTheDocument();
  });

  it("says how to send, and Enter really does send while Shift+Enter does not", async () => {
    const fetchMock = mockFetch(api());
    const user = await open();
    expect(screen.getByText("Enter to send · Shift+Enter for new line")).toBeInTheDocument();

    await user.type(box(), "line one{Shift>}{Enter}{/Shift}line two");
    expect(chatCalls(fetchMock)).toHaveLength(0);
    await user.keyboard("{Enter}");
    expect(await screen.findByText("ok")).toBeInTheDocument();
    expect(chatCalls(fetchMock)).toHaveLength(1);
  });

  it("shows a typing indicator while a reply is on its way, and says so in words", async () => {
    let release!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    mockFetch(api(() => pending));
    const user = await open();

    await say(user, "hello");

    expect(await screen.findByText("The assistant is replying…")).toBeInTheDocument();
    expect(document.querySelector(".typing-dots")).not.toBeNull();
    release(json({ reply: "done", ended: false }));
    expect(await screen.findByText("done")).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector(".typing-dots")).toBeNull());
  });

  it("shows an ordinary reply as a plain card, with no grounded accent", async () => {
    mockFetch(api());
    const user = await open();
    await say(user, "hello");
    await screen.findByText("ok");

    expect(screen.getByText("ok").closest("article")).not.toHaveClass("is-grounded");
    expect(screen.getByText(GREETING).closest("article")).not.toHaveClass("is-grounded");
  });

  it("asks for the message with exactly the words 'Type your message'", async () => {
    mockFetch(api());
    await open();

    expect(screen.getByPlaceholderText("Type your message")).toBe(box());
    expect(screen.queryByPlaceholderText(/customer/i)).not.toBeInTheDocument();
  });

  it("shows one time marker above the first message, and no more as the conversation grows", async () => {
    mockFetch(api());
    const user = await open();
    expect(screen.getAllByText(/^Today · /)).toHaveLength(1);

    await say(user, "hello");
    await screen.findByText("ok");
    await say(user, "and again");
    await waitFor(() => expect(transcript().getAllByText("ok")).toHaveLength(2));

    expect(screen.getAllByText(/^Today · /)).toHaveLength(1);
  });

  it("can start a new conversation at any time from the header", async () => {
    let sessions = 0;
    mockFetch((url) => {
      if (url === "/api/session") {
        sessions += 1;
        return json({ session_id: `s${sessions}`, greeting: `Greeting ${sessions}` });
      }
      return json({ detail: "not found" }, 404);
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Greeting 1");

    await user.click(screen.getByRole("button", { name: "New conversation" }));

    expect(await screen.findByText("Greeting 2")).toBeInTheDocument();
    expect(screen.queryByText("Greeting 1")).not.toBeInTheDocument();
  });

  it("is a plain customer conversation when the server has no evaluator view", async () => {
    mockFetch(api());
    const user = await open();
    await say(user, "hello");
    await screen.findByText("ok");

    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.queryByText("SOP inspector")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More actions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Workflow inspector" })).not.toBeInTheDocument();
    expect(screen.queryByText("Grounded in claim record")).not.toBeInTheDocument();
  });
});
