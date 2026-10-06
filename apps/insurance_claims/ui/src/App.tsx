import { useEffect, useRef, useState } from "react";
import { AppHeader } from "./AppHeader";
import { Chat } from "./Chat";
import { hasGroundedAnswer } from "./format";
import { InspectorBoundary } from "./InspectorBoundary";
import { InspectorHeader } from "./inspector/InspectorHeader";
import { SopInspector } from "./inspector/SopInspector";
import { useEventTimes } from "./inspector/useEventTimes";
import { ScenarioMenu } from "./ScenarioMenu";
import type { Scenario } from "./scenarios";
import { type DebugView, MAX_MESSAGE_CHARS } from "./types";
import { useConversation } from "./useConversation";
import { useInspector } from "./useInspector";

/** The reply revisions the SOP inspector confirms were answered from the claim record.
 *
 * The customer-facing response carries only the reply text, so this indicator is read from the
 * inspector data and only exists while the server has the inspector on. Each view is tied to the
 * revision it was fetched for, which is the reply it describes, so a later turn can never move
 * the mark onto the wrong message. */
function useGroundedReplies(
  sessionId: string | null,
  view: DebugView | null,
  viewRevision: number | null,
): ReadonlySet<number> {
  const [revisions, setRevisions] = useState<ReadonlySet<number>>(() => new Set());

  useEffect(() => {
    setRevisions(new Set()); // a different session starts with no marks
  }, [sessionId]);

  useEffect(() => {
    if (view === null || viewRevision === null || !hasGroundedAnswer(view)) return;
    setRevisions((previous) => new Set(previous).add(viewRevision));
  }, [view, viewRevision]);

  return revisions;
}

export default function App() {
  const conversation = useConversation();
  const inspector = useInspector(conversation.sessionId, conversation.revision);
  const showInspector = inspector.status === "on";
  const groundedRevisions = useGroundedReplies(
    conversation.sessionId,
    inspector.view,
    inspector.viewRevision,
  );
  const eventTimes = useEventTimes(conversation.sessionId, inspector.view);
  // The verified state is only known while the SOP inspector is available; the customer-facing
  // API deliberately does not carry it.
  const identityVerified = inspector.view?.verification.verified ?? false;
  const verifiedAs = inspector.view?.verification.verified_as ?? null;

  // On narrow screens the inspector is a drawer; on wide screens this state has no effect.
  const [drawerOpen, setDrawerOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!drawerOpen) return;
    closeRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setDrawerOpen(false);
        toggleRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  function closeDrawer() {
    setDrawerOpen(false);
    toggleRef.current?.focus();
  }

  async function runScenario(scenario: Scenario) {
    // A new conversation, with the message ready but not sent: the evaluator presses Send.
    const opened = await conversation.start(scenario.consentScenario);
    if (opened) conversation.setInput(scenario.message);
  }

  return (
    <div className="shell">
      <AppHeader
        onNewConversation={() => void conversation.start()}
        starting={conversation.starting}
        menu={
          showInspector ? (
            <ScenarioMenu disabled={conversation.starting} onPick={(s) => void runScenario(s)} />
          ) : null
        }
        hasInspector={showInspector}
        drawerOpen={drawerOpen}
        onToggleDrawer={() => setDrawerOpen((open) => !open)}
        toggleRef={toggleRef}
      />

      <main className={showInspector ? "main with-inspector" : "main"}>
        <Chat
          messages={conversation.messages}
          input={conversation.input}
          onInput={conversation.setInput}
          onSend={() => void conversation.send()}
          onRestart={() => void conversation.start()}
          busy={conversation.busy}
          starting={conversation.starting}
          ended={conversation.ended}
          ready={conversation.sessionId !== null}
          error={conversation.error}
          maxLength={MAX_MESSAGE_CHARS}
          sessionLabel={conversation.sessionId ? conversation.sessionId.slice(0, 8) : null}
          groundedRevisions={groundedRevisions}
          identityVerified={identityVerified}
          verifiedAs={verifiedAs}
        />

        {showInspector && (
          <>
            {drawerOpen && <div className="backdrop" onClick={closeDrawer} aria-hidden="true" />}
            <aside
              id="sop-inspector"
              className={drawerOpen ? "inspector open" : "inspector"}
              aria-label="SOP inspector"
            >
              <InspectorHeader onClose={closeDrawer} closeRef={closeRef} />
              <InspectorBoundary resetKey={inspector.view}>
                <SopInspector view={inspector.view} times={eventTimes} />
              </InspectorBoundary>
            </aside>
          </>
        )}
      </main>
    </div>
  );
}
