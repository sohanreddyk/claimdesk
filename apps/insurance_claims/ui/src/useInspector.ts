import { useEffect, useRef, useState } from "react";
import { getDebug } from "./api";
import type { DebugView } from "./types";

/** "unknown" until the first answer: the server either serves an inspector view or answers 404
 * (inspector off). There is no separate setting in the UI to keep in sync with the server. */
export type InspectorStatus = "unknown" | "on" | "off";

export interface InspectorState {
  status: InspectorStatus;
  view: DebugView | null;
}

/** Fetches the inspector view after the session opens and after every turn (`revision`). It
 * never polls, and it stops asking once the server has said the inspector is off. */
export function useInspector(sessionId: string | null, revision: number): InspectorState {
  const [status, setStatus] = useState<InspectorStatus>("unknown");
  const [view, setView] = useState<DebugView | null>(null);
  const off = useRef(false);
  const seenOnce = useRef(false);

  useEffect(() => {
    if (off.current) return;
    if (!sessionId) {
      setView(null); // a new session is on its way: do not show the old one's workings
      return;
    }
    let cancelled = false;
    getDebug(sessionId)
      .then((next) => {
        if (cancelled) return;
        if (next === null) {
          // Only the very first answer decides: after the inspector has been seen, a 404 can
          // also mean the session expired, which must not hide the inspector.
          if (!seenOnce.current) {
            off.current = true;
            setStatus("off");
          }
          return;
        }
        seenOnce.current = true;
        setStatus("on");
        setView(next);
      })
      .catch(() => {
        // A failed refresh keeps whatever is on screen.
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, revision]);

  return { status, view };
}
