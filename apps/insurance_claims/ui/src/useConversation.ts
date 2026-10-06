import { useCallback, useEffect, useRef, useState } from "react";
import { createSession, errorText, sendMessage, statusOf } from "./api";

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
}

export interface Conversation {
  sessionId: string | null;
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  /** A reply is on its way. */
  busy: boolean;
  /** A session is being created. */
  starting: boolean;
  /** The conversation is over (finished, or the session expired). */
  ended: boolean;
  error: string | null;
  send: () => Promise<void>;
  /** Begin a new session. The optional consent scenario only has an effect when the server's
   * inspector is on. */
  start: (consentScenario?: string) => Promise<void>;
}

/**
 * Everything about one conversation, in memory only: nothing is written to localStorage or
 * cookies, so a refresh starts over and no identity details linger in the browser.
 */
export function useConversation(): Conversation {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(true);
  const [ended, setEnded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Bumped whenever a new session begins, so a slow response from an old session can never be
  // added to the new transcript.
  const generation = useRef(0);
  const nextId = useRef(1);
  const started = useRef(false);

  const start = useCallback(async (consentScenario?: string) => {
    const gen = ++generation.current;
    setStarting(true);
    setBusy(false);
    setEnded(false);
    setError(null);
    setSessionId(null);
    setMessages([]);
    setInput("");
    try {
      const session = await createSession(consentScenario);
      if (gen !== generation.current) return;
      setSessionId(session.session_id);
      setMessages([{ id: nextId.current++, role: "assistant", text: session.greeting }]);
    } catch (err) {
      if (gen !== generation.current) return;
      setError(errorText(statusOf(err)));
    } finally {
      if (gen === generation.current) setStarting(false);
    }
  }, []);

  useEffect(() => {
    // Guards against React StrictMode running effects twice in development, which would
    // otherwise create two sessions.
    if (started.current) return;
    started.current = true;
    void start();
  }, [start]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy || ended || starting || !sessionId) return;

    const gen = generation.current;
    const sent: ChatMessage = { id: nextId.current++, role: "user", text };
    setMessages((prev) => [...prev, sent]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const response = await sendMessage(sessionId, text);
      if (gen !== generation.current) return;
      setMessages((prev) => [
        ...prev,
        { id: nextId.current++, role: "assistant", text: response.reply },
      ]);
      if (response.ended) setEnded(true);
    } catch (err) {
      if (gen !== generation.current) return;
      const status = statusOf(err);
      setError(errorText(status));
      if (status === 404) {
        setEnded(true); // the session is gone: keep the transcript, offer a fresh start
      } else {
        // The message did not go through: take it back out and return it to the box.
        setMessages((prev) => prev.filter((m) => m.id !== sent.id));
        setInput((current) => current || text);
      }
    } finally {
      if (gen === generation.current) setBusy(false);
    }
  }, [input, busy, ended, starting, sessionId]);

  return { sessionId, messages, input, setInput, busy, starting, ended, error, send, start };
}
