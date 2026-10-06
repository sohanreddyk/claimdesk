import { useId } from "react";

/**
 * The ClaimDesk mark: a shield (trust, verification) carrying a document sheet with a check
 * (a claim, checked). Original artwork, inline, no dependency. The blue-to-teal gradient lives
 * here and nowhere else in the interface; its colours come from the design tokens.
 */
export function BrandMark({ size = 32 }: { size?: number }) {
  const gradient = `claimdesk-${useId().replace(/:/g, "")}`;
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      className="brand-mark"
    >
      <defs>
        <linearGradient id={gradient} x1="5" y1="3" x2="27" y2="29" gradientUnits="userSpaceOnUse">
          <stop offset="0" style={{ stopColor: "var(--brand-700)" }} />
          <stop offset="1" style={{ stopColor: "var(--teal-600)" }} />
        </linearGradient>
      </defs>
      <path
        d="M16 2.5 5 6.3v8.2c0 6.6 4.3 11.2 11 15 6.7-3.8 11-8.4 11-15V6.3L16 2.5Z"
        fill={`url(#${gradient})`}
      />
      <path
        d="M11.5 9.5h6.2l3.3 3.3V21a.5.5 0 0 1-.5.5h-9a.5.5 0 0 1-.5-.5V10a.5.5 0 0 1 .5-.5Z"
        style={{ fill: "var(--surface)" }}
      />
      <path d="M17.7 9.5v3.3H21" style={{ fill: "var(--brand-100)" }} />
      <path
        d="m13.7 16.4 1.9 1.9 3.5-4"
        fill="none"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ stroke: "var(--brand-700)" }}
      />
    </svg>
  );
}
