import { JobEvent } from "../types";

interface EventTimelineProps {
  events: JobEvent[];
}

export function EventTimeline({ events }: EventTimelineProps) {
  if (!events.length) {
    return <p className="muted">No events yet.</p>;
  }
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.id} className={`timeline-event timeline-${event.event}`}>
          <div className="timeline-meta">
            <time dateTime={event.timestamp}>{formatTimestamp(event.timestamp)}</time>
            <span className="timeline-type">{event.event}</span>
          </div>
          <div className="timeline-body">
            <p>{event.message || ""}</p>
            {Object.keys(event.data || {}).length ? (
              <pre>{JSON.stringify(event.data, null, 2)}</pre>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function formatTimestamp(input: string): string {
  if (!input) {
    return "";
  }
  try {
    const date = new Date(input);
    return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
  } catch (error) {
    return input;
  }
}
