import { useEffect, useState } from "react";
import type { DebugView } from "../types";

/**
 * When the evaluator view first received each audit event, by event number.
 *
 * Audit events deliberately carry no wall-clock time (it keeps the backend deterministic), so the
 * times shown in the activity timeline are when this page saw them: within a turn, that is
 * when the reply arrived. They are reset whenever a different session starts.
 */
export function useEventTimes(
  sessionId: string | null,
  view: DebugView | null,
): ReadonlyMap<number, number> {
  const [times, setTimes] = useState<ReadonlyMap<number, number>>(() => new Map());

  useEffect(() => {
    setTimes(new Map());
  }, [sessionId]);

  useEffect(() => {
    if (view === null) return;
    setTimes((previous) => {
      const unseen = view.events.filter((event) => !previous.has(event.seq));
      if (unseen.length === 0) return previous;
      const now = Date.now();
      const next = new Map(previous);
      for (const event of unseen) next.set(event.seq, now);
      return next;
    });
  }, [view]);

  return times;
}
