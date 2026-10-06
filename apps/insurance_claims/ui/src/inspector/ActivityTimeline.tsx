import { formatTime } from "../format";
import { AlertIcon, ArrowRightIcon, CheckIcon, DiamondIcon, DotIcon } from "../icons";
import type { DebugView } from "../types";
import { type TimelineIcon, buildTimeline } from "./events";
import { Disclosure, Section } from "./parts";

const RECENT = 10;

function Glyph({ kind }: { kind: TimelineIcon }) {
  switch (kind) {
    case "check":
      return <CheckIcon size={10} strokeWidth={2.4} />;
    case "arrow":
      return <ArrowRightIcon size={10} strokeWidth={2.2} />;
    case "diamond":
      return <DiamondIcon size={9} strokeWidth={2} />;
    case "alert":
      return <AlertIcon size={10} strokeWidth={2} />;
    case "dot":
      return <DotIcon size={8} />;
  }
}

/** Recent events as a small timeline: time, a marker joined to the next by a line, and a
 * sentence. Times are when this page received the events (see useEventTimes). A sent email is
 * listed beneath, with its text behind a disclosure. */
export function ActivityTimeline({
  view,
  times,
}: {
  view: DebugView;
  times: ReadonlyMap<number, number>;
}) {
  const items = buildTimeline(view.events);
  const recent = items.slice(-RECENT);

  return (
    <Section title="Activity">
      {items.length === 0 ? (
        <p className="muted">No activity yet</p>
      ) : (
        <ol className="timeline" aria-label="Recent activity">
          {recent.map((item) => {
            const at = times.get(item.seq);
            return (
              <li key={item.seq} data-tone={item.tone}>
                {at === undefined ? (
                  <span className="timeline-time" aria-hidden="true" />
                ) : (
                  <time className="timeline-time" dateTime={new Date(at).toISOString()}>
                    {formatTime(at)}
                  </time>
                )}
                <span className="timeline-rail" aria-hidden="true">
                  <span className="timeline-icon">
                    <Glyph kind={item.icon} />
                  </span>
                </span>
                <span className="timeline-text">{item.text}</span>
              </li>
            );
          })}
        </ol>
      )}
      {items.length > recent.length && (
        <p className="muted small">
          {`Showing the latest ${RECENT} of ${items.length}. The full trail is under Technical details.`}
        </p>
      )}

      {view.outbox.length > 0 && (
        <>
          <h4>Emails</h4>
          <ul className="log" aria-label="Emails">
            {view.outbox.map((mail, index) => (
              <li key={index}>
                <div>
                  <span className="muted">To </span>
                  <code>{mail.to}</code>
                </div>
                <div>{mail.subject}</div>
                <Disclosure label="View message">
                  <pre className="mail-body">{mail.body}</pre>
                </Disclosure>
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}
