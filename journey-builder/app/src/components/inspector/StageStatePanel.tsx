type StageStatePanelProps = {
  stageKey: string;
  stageLabel: string;
  stageState: "current" | "stale" | "missing";
  confidence: string;
  classifiedAt: string;
};

function stateCopy(stageState: "current" | "stale" | "missing") {
  switch (stageState) {
    case "current":
      return "Stage result is current for the active journey version.";
    case "stale":
      return "Stage result exists but should be revisited because upstream state changed.";
    case "missing":
      return "No current stage result exists yet for the routed journey.";
    default:
      return "";
  }
}

export function StageStatePanel({ stageKey, stageLabel, stageState, confidence, classifiedAt }: StageStatePanelProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Current stage</h3>
          <p className="panel-copy">Latest stage result for the current journey.</p>
        </div>
      </div>
      <div className="preview-card">
        <strong>
          {stageLabel} <span className={`state-pill state-pill--${stageState}`}>{stageState}</span>
        </strong>
        <span>
          {stageKey} · confidence {confidence} · classified {classifiedAt}
        </span>
        <p>{stateCopy(stageState)}</p>
      </div>
    </article>
  );
}
