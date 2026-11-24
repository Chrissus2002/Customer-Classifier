import type { JourneyChange } from "../../data/journeys";

type RecentChangesPanelProps = {
  changes: JourneyChange[];
};

export function RecentChangesPanel({ changes }: RecentChangesPanelProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Recent activity</h3>
          <p className="panel-copy">Latest changes across active journeys.</p>
        </div>
      </div>
      <div className="timeline-list">
        {changes.map((item) => (
          <div key={`${item.time}-${item.item}`} className="timeline-item">
            <span className="timeline-time">{item.time}</span>
            <div>
              <strong>{item.item}</strong>
              <p>{item.detail}</p>
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}
