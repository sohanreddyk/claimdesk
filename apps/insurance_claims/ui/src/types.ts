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
