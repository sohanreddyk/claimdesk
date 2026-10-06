import type { ChatResponse, DebugView, SessionResponse } from "./types";

/** A failed request. Only the status is kept: server error text is never shown to the caller. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0); // the network or the server is unreachable
  }
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(response.status || 500);
  }
}

function post(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function createSession(consentScenario?: string): Promise<SessionResponse> {
  const body = consentScenario ? { consent_scenario: consentScenario } : {};
  return request<SessionResponse>("/api/session", post(body));
}

export function sendMessage(sessionId: string, message: string): Promise<ChatResponse> {
  return request<ChatResponse>("/api/chat", post({ session_id: sessionId, message }));
}

/** The inspector view, or null when the server does not offer one (inspector off, or the
 * session is gone). Other failures are thrown, including a 200 that is not an inspector view,
 * so a malformed answer is treated like any failed refresh. */
export async function getDebug(sessionId: string): Promise<DebugView | null> {
  try {
    const view = await request<unknown>(`/api/session/${encodeURIComponent(sessionId)}/debug`, {
      method: "GET",
    });
    if (!isDebugView(view)) throw new ApiError(502);
    return view;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

function isDebugView(value: unknown): value is DebugView {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.session_id === "string" &&
    typeof candidate.phase === "string" &&
    typeof candidate.verification === "object" &&
    candidate.verification !== null
  );
}

/** The plain-language message for a failure. Fixed text, chosen by status only. */
export function errorText(status: number): string {
  switch (status) {
    case 0:
      return "Could not reach the server. Check your connection and try again.";
    case 404:
      return "This session has expired. Please start a new conversation.";
    case 413:
    case 422:
      return "That message could not be sent. Try a shorter one.";
    case 503:
      return "The service is busy. Please try again in a moment.";
    default:
      return "Something went wrong. Please try again.";
  }
}

export function statusOf(error: unknown): number {
  return error instanceof ApiError ? error.status : 0;
}
