import { ShieldCheckIcon } from "../icons";

/** Shown only under a claim answer the SOP inspector confirms was read from the claim record. */
export function GroundedBadge() {
  return (
    <p className="grounded" title="Response generated from verified claim data.">
      <ShieldCheckIcon size={12} strokeWidth={1.8} />
      Grounded in claim record
    </p>
  );
}
