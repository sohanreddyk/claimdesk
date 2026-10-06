/** Prepared first messages for the evaluator. Choosing one starts a new conversation and fills
 * the message box: it is not sent until the evaluator presses Send, so what runs is visible. */
export interface Scenario {
  id: string;
  label: string;
  /** The consent scenario the new session runs with. Always explicit, so a button behaves the
   * same whatever the server's own default is. */
  consentScenario: "default" | "timeout";
  message: string;
  hint: string;
}

const MARGARET =
  "I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my " +
  "denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.";

const DAVID =
  "I'm David Chen, Margaret's son. Her DOB is 1985-03-15, SSN last four 4472, " +
  "and her phone is 650-521-2836.";

export const SCENARIOS: Scenario[] = [
  {
    id: "margaret",
    label: "Margaret demo",
    consentScenario: "default",
    message: MARGARET,
    hint: "Verifies from one message and explains the denial.",
  },
  {
    id: "frustrated",
    label: "Frustrated caller",
    consentScenario: "default",
    message:
      "This is ridiculous, I've been trying to get an answer about my claim for weeks and " +
      "nobody helps me! I'm Margaret Chen, DOB 1985-03-15, SSN last four 4472.",
    hint: "Acknowledges the frustration, then verifies.",
  },
  {
    id: "out-of-scope",
    label: "Out-of-scope retries",
    consentScenario: "default",
    message: "What's the weather like in Seattle today?",
    hint: "Send it a few times to reach the out-of-scope limit.",
  },
  {
    id: "ssn-refusal",
    label: "SSN refusal",
    consentScenario: "default",
    message:
      "I'm Margaret Chen and my date of birth is 1985-03-15, but I'm not comfortable giving " +
      "out my SSN. I'd rather not share it.",
    hint: "Refuse again to see what repeated refusals do.",
  },
  {
    id: "rep-approved",
    label: "Representative approved",
    consentScenario: "default",
    message: DAVID,
    hint: "The policyholder's consent is approved.",
  },
  {
    id: "rep-timeout",
    label: "Representative timeout",
    consentScenario: "timeout",
    message: DAVID,
    hint: "The policyholder's consent times out.",
  },
];
