import type { DebugView } from "../types";
import { ActivityTimeline } from "./ActivityTimeline";
import { CurrentCaseCard } from "./CurrentCaseCard";
import { IdentityStatus } from "./IdentityStatus";
import { RememberedContext } from "./RememberedContext";
import { SafetyStatus } from "./SafetyStatus";
import { TechnicalDetails } from "./TechnicalDetails";
import { WorkflowPanel } from "./WorkflowStepper";

/** The evaluator's view of what the agent is doing, as readable sections. Every identity value
 * arrives already masked from the server; this only lays the data out. */
export function SopInspector({
  view,
  times,
}: {
  view: DebugView | null;
  times: ReadonlyMap<number, number>;
}) {
  if (!view) {
    return (
      <p className="system-note padded" role="status">
        Waiting for a session…
      </p>
    );
  }

  return (
    <div>
      <WorkflowPanel view={view} />
      <IdentityStatus view={view} />
      <CurrentCaseCard view={view} />
      <RememberedContext view={view} />
      <SafetyStatus view={view} />
      <ActivityTimeline view={view} times={times} />
      <TechnicalDetails view={view} />
    </div>
  );
}
