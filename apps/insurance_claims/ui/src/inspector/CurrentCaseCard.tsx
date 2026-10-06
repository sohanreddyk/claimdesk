import { DocumentIcon } from "../icons";
import type { DebugView } from "../types";
import { Chip, Rows, Section } from "./parts";
import { toCase } from "./viewModel";

/** The claim being handled, as a small snapshot: the claim number and its status at a glance,
 * the type, and whatever else is known. Before a claim is chosen it is an intentional empty
 * state, not a line of text. */
export function CurrentCaseCard({ view }: { view: DebugView }) {
  const claim = toCase(view);

  return (
    <Section title="Current case">
      {!claim.selected ? (
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">
            <DocumentIcon size={16} />
          </span>
          <p className="empty-title">No claim selected</p>
          <p className="empty-text">Claim details appear after verification and resolution.</p>
        </div>
      ) : (
        <div className="case-card">
          <div className="case-card-head">
            <code className="case-id">{claim.claimId}</code>
            {claim.status && <Chip tone={claim.status.tone}>{claim.status.label}</Chip>}
          </div>
          {claim.caseType && <p className="case-type">{claim.caseType}</p>}
          {claim.rows.length > 0 && <Rows rows={claim.rows} />}
        </div>
      )}
    </Section>
  );
}
