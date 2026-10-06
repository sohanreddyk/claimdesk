import { Chat } from "./Chat";
import { Inspector } from "./Inspector";
import { InspectorBoundary } from "./InspectorBoundary";
import { ScenarioBar } from "./ScenarioBar";
import type { Scenario } from "./scenarios";
import { MAX_MESSAGE_CHARS } from "./types";
import { useConversation } from "./useConversation";
import { useInspector } from "./useInspector";

export default function App() {
  const conversation = useConversation();
  const inspector = useInspector(conversation.sessionId, conversation.revision);
  const showInspector = inspector.status === "on";

  async function runScenario(scenario: Scenario) {
    // A new conversation, with the message ready but not sent: the evaluator presses Send.
    const opened = await conversation.start(scenario.consentScenario);
    if (opened) conversation.setInput(scenario.message);
  }

  return (
    <main className={showInspector ? "app with-inspector" : "app"}>
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
      />
      {showInspector && (
        <aside className="inspector" aria-label="Evaluator inspector">
          <header className="inspector-header">
            <h2>Inspector</h2>
            <p className="muted">Evaluator view. Identity values are masked.</p>
          </header>
          <ScenarioBar disabled={conversation.starting} onPick={(s) => void runScenario(s)} />
          <InspectorBoundary resetKey={inspector.view}>
            <Inspector view={inspector.view} />
          </InspectorBoundary>
        </aside>
      )}
    </main>
  );
}
