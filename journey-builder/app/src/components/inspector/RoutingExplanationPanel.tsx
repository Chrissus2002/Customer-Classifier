type RoutingExplanationPanelProps = {
  rule: string;
  configVersion: string;
  reason: string;
};

export function RoutingExplanationPanel({ rule, configVersion, reason }: RoutingExplanationPanelProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Routing explanation</h3>
          <p className="panel-copy">Why this contact ended up in the current journey.</p>
        </div>
      </div>
      <div className="stack">
        <div className="preview-card">
          <strong>{rule}</strong>
          <span>Routing config {configVersion}</span>
          <p>{reason}</p>
        </div>
      </div>
    </article>
  );
}
