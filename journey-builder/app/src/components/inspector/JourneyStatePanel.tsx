type JourneyStatePanelProps = {
  journeyLabel: string;
  lastActivity: string;
  lastInbound: string;
};

export function JourneyStatePanel({ journeyLabel, lastActivity, lastInbound }: JourneyStatePanelProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Current journey</h3>
          <p className="panel-copy">The current routed journey for this contact.</p>
        </div>
      </div>
      <dl className="journey-stats journey-stats--single">
        <div>
          <dt>Journey</dt>
          <dd>{journeyLabel}</dd>
        </div>
        <div>
          <dt>Last activity</dt>
          <dd>{lastActivity}</dd>
        </div>
        <div>
          <dt>Last inbound</dt>
          <dd>{lastInbound}</dd>
        </div>
      </dl>
    </article>
  );
}
