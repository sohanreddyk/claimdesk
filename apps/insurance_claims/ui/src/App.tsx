import { MAX_MESSAGE_CHARS } from "./types";
import { Chat } from "./Chat";
import { useConversation } from "./useConversation";

export default function App() {
  const conversation = useConversation();

  return (
    <main className="app">
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
    </main>
  );
}
