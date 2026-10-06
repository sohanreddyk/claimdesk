import { CheckIcon, ShieldIcon } from "../icons";
import type { DebugView } from "../types";
import { Chip, Rows, Section } from "./parts";
import { toIdentity } from "./viewModel";

/** A compact status block: whether the caller is verified and how many of the required factors
 * matched, drawn as a small progress bar and also written out. The values shown for supplied
 * details are masked by the server. */
export function IdentityStatus({ view }: { view: DebugView }) {
  const identity = toIdentity(view);
  const tone = identity.verified ? "good" : "neutral";

  return (
    <Section title="Identity">
      <div className={`status-block status-${tone}`}>
        <div className="status-block-head">
          <span className="status-icon" aria-hidden="true">
            {identity.verified ? <CheckIcon size={14} strokeWidth={2.2} /> : <ShieldIcon size={14} />}
          </span>
          <Chip tone={tone}>{identity.status}</Chip>
        </div>
        <Rows rows={[["Verification", identity.summary]]} />
        <div
          className="progress"
          role="progressbar"
          aria-label="Verification factors matched"
          aria-valuemin={0}
          aria-valuemax={identity.required}
          aria-valuenow={identity.matched}
          aria-valuetext={identity.progressLabel}
        >
          {Array.from({ length: identity.required }, (_, index) => (
            <span key={index} data-filled={index < identity.matched} />
          ))}
        </div>
      </div>

      {identity.details.length > 0 && <Rows rows={identity.details} />}

      {identity.supplied.length > 0 && (
        <ul className="factors" aria-label="Details supplied">
          {identity.supplied.map((factor) => (
            <li key={factor.key}>
              <span>{factor.label}</span>
              <code>{factor.value}</code>
              {factor.matched && <Chip tone="good">Matched</Chip>}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
