import { CheckIcon, ShieldCheckIcon } from "../icons";

/** A compact strip that says, in the product itself, what the SOP guarantees: protected claim
 * information stays protected until identity is verified. It switches to "Identity verified"
 * only when the SOP inspector reports that the caller is verified, since the customer-facing
 * API does not carry that state. */
export function SecureSessionBanner({
  verified,
  verifiedAs,
}: {
  verified: boolean;
  verifiedAs: string | null;
}) {
  return (
    <div
      className={verified ? "secure-banner secure-verified" : "secure-banner"}
      aria-live="polite"
    >
      <span className="secure-icon" aria-hidden="true">
        {verified ? <CheckIcon size={14} strokeWidth={2.2} /> : <ShieldCheckIcon size={14} />}
      </span>
      {verified ? (
        <p>
          <strong>Identity verified</strong>
          {verifiedAs === "representative" ? " (representative)" : ""}
          <span> · Protected claim information can now be discussed.</span>
        </p>
      ) : (
        <p>
          <strong>Secure claims conversation</strong>
          <span>
            {" "}
            · Identity verification is required before protected claim information can be
            discussed.
          </span>
        </p>
      )}
    </div>
  );
}
