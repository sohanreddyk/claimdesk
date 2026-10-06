import type { ReactNode, SVGProps } from "react";

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  size?: number;
}

/** A small stroke icon on a 16x16 grid. Decorative: the words next to it carry the meaning. */
function Icon({ size = 16, children, ...rest }: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

const SHIELD = "M8 1.8 3 3.6v4c0 3 2 5.2 5 6.6 3-1.4 5-3.6 5-6.6v-4L8 1.8Z";

export const ShieldIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d={SHIELD} />
  </Icon>
);

export const ShieldCheckIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d={SHIELD} />
    <path d="m5.8 8.1 1.6 1.6 3-3.2" />
  </Icon>
);

export const CheckIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3.5 8.5l3 3 6-7" />
  </Icon>
);

export const ArrowRightIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" />
  </Icon>
);

export const DiamondIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M8 2.5 13.5 8 8 13.5 2.5 8 8 2.5Z" />
  </Icon>
);

export const AlertIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M8 2 14.2 13H1.8L8 2ZM8 6.5v3M8 11.3v.1" />
  </Icon>
);

export const DocumentIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 1.8h5l3 3v9.4H4V1.8ZM9 1.8v3h3M6 8h4M6 10.5h4" />
  </Icon>
);

export const CopyIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
    <path d="M10.5 3.5V3A1.5 1.5 0 0 0 9 1.5H4A1.5 1.5 0 0 0 2.5 3v5A1.5 1.5 0 0 0 4 9.5h.5" />
  </Icon>
);

export const ChevronDownIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3.5 6l4.5 4.5L12.5 6" />
  </Icon>
);

export const MoreIcon = (props: IconProps) => (
  <Icon {...props} stroke="none" fill="currentColor">
    <circle cx="3" cy="8" r="1.4" />
    <circle cx="8" cy="8" r="1.4" />
    <circle cx="13" cy="8" r="1.4" />
  </Icon>
);

export const DotIcon = (props: IconProps) => (
  <Icon {...props} stroke="none" fill="currentColor">
    <circle cx="8" cy="8" r="2.2" />
  </Icon>
);
