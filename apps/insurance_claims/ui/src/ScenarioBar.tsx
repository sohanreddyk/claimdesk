import type { Scenario } from "./scenarios";
import { SCENARIOS } from "./scenarios";

interface ScenarioBarProps {
  disabled: boolean;
  onPick: (scenario: Scenario) => void;
}

export function ScenarioBar({ disabled, onPick }: ScenarioBarProps) {
  return (
    <section className="inspector-section" aria-label="Scenarios">
      <h3>Scenarios</h3>
      <p className="muted">
        Starts a new conversation and fills the message box. Press Send to run it.
      </p>
      <ul className="scenarios">
        {SCENARIOS.map((scenario) => (
          <li key={scenario.id}>
            <button type="button" disabled={disabled} onClick={() => onPick(scenario)}>
              {scenario.label}
            </button>
            <span className="muted">{scenario.hint}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
