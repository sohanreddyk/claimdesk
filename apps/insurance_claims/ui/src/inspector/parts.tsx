import { isValidElement, useId, useState } from "react";
import type { ReactNode } from "react";
import { show } from "../format";
import { ChevronDownIcon } from "../icons";
import type { StatusTone } from "./tone";

/** One titled block of the inspector. Sections are separated by spacing and a hairline, not
 * boxed in cards. A short subtitle can say what kind of information the section holds. */
export function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section className="panel" aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {subtitle && <p className="panel-sub">{subtitle}</p>}
      {children}
    </section>
  );
}

/** A short status label. The text always says the status: colour only reinforces it. */
export function Chip({
  tone = "neutral",
  children,
}: {
  tone?: StatusTone;
  children: ReactNode;
}) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

/** Label and value pairs. A value is shown as plain text unless it is already an element. */
export function Rows({ rows }: { rows: [label: string, value: unknown][] }) {
  return (
    <dl className="rows">
      {rows.map(([label, value]) => (
        <div key={label} className="row">
          <dt>{label}</dt>
          <dd>{isValidElement(value) ? value : show(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A small inline disclosure for a little extra detail (for example an email's text). */
export function Disclosure({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="disclosure">
      <button
        type="button"
        className="link"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((current) => !current)}
      >
        {label}
        <ChevronDownIcon className="chevron" size={10} strokeWidth={1.8} />
      </button>
      {open && <div id={id}>{children}</div>}
    </div>
  );
}

/** A collapsed section whose heading is the button that opens it. Opening fades the content in;
 * closing removes it, so the collapsed section costs nothing in the page. */
export function AccordionSection({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  return (
    <section className="panel panel-quiet">
      <h3>
        <button
          type="button"
          className="accordion-button"
          aria-expanded={open}
          aria-controls={contentId}
          onClick={() => setOpen((current) => !current)}
        >
          {title}
          <ChevronDownIcon className="chevron" size={12} strokeWidth={1.8} />
        </button>
      </h3>
      {open && (
        <div id={contentId} className="accordion-body">
          {children}
        </div>
      )}
    </section>
  );
}
