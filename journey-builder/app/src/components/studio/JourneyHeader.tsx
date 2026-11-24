import type { JourneyStudioRecord } from "../../data/studio";

type JourneyHeaderProps = {
  record: JourneyStudioRecord;
};

export function JourneyHeader({ record }: JourneyHeaderProps) {
  return (
    <article className="panel subtle-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">{record.journeyKey}</span>
          <h3>{record.journeyLabel}</h3>
          <p className="panel-copy">Stages, prompt, and version details for this journey.</p>
        </div>
      </div>
      <dl className="journey-stats journey-stats--wide">
        <div>
          <dt>Active</dt>
          <dd>{record.activeVersion}</dd>
        </div>
        <div>
          <dt>Draft</dt>
          <dd>{record.draftVersion}</dd>
        </div>
        <div>
          <dt>Unsaved</dt>
          <dd>{record.unsavedChanges}</dd>
        </div>
      </dl>
    </article>
  );
}
