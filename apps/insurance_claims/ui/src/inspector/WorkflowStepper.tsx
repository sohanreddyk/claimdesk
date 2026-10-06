import { CheckIcon } from "../icons";
import type { DebugView } from "../types";
import { Chip, Rows, Section } from "./parts";
import { type StepState, toWorkflow } from "./viewModel";

const STATE_NOTE: Record<StepState, string> = {
  done: " (completed)",
  current: " (current step)",
  upcoming: " (upcoming)",
};

function StepMarker({ state }: { state: StepState }) {
  return (
    <span className={`step-marker step-${state}`} aria-hidden="true">
      {state === "done" && <CheckIcon size={10} strokeWidth={2.4} />}
    </span>
  );
}

/** The four phases as a vertical stepper joined by a line. A step's state is stated in words for
 * assistive technology as well as drawn, so nothing depends on colour. Changes between states
 * ease over a short transition. */
export function WorkflowStepper({ steps }: { steps: ReturnType<typeof toWorkflow>["steps"] }) {
  return (
    <ol className="stepper" aria-label="Workflow phases">
      {steps.map((step, index) => (
        <li
          key={step.id}
          data-state={step.state}
          aria-current={step.state === "current" ? "step" : undefined}
        >
          <span className="step-rail" aria-hidden="true">
            <StepMarker state={step.state} />
            {index < steps.length - 1 && (
              <span className="step-line" data-filled={step.state === "done"} />
            )}
          </span>
          <span className="step-label">{step.label}</span>
          <span className="sr-only">{STATE_NOTE[step.state]}</span>
        </li>
      ))}
    </ol>
  );
}

export function WorkflowPanel({ view }: { view: DebugView }) {
  const workflow = toWorkflow(view);
  return (
    <Section title="Workflow">
      <WorkflowStepper steps={workflow.steps} />
      <Rows
        rows={[
          ["Current step", workflow.currentLabel],
          ["Turns", workflow.turns],
          ["Guard", <Chip tone={workflow.guard.tone}>{workflow.guard.label}</Chip>],
        ]}
      />
    </Section>
  );
}
