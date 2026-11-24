import type { StageDefinition } from "../../data/studio";
import { StageRowEditor } from "./StageRowEditor";

type StageListEditorProps = {
  stages: StageDefinition[];
};

export function StageListEditor({ stages }: StageListEditorProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Stages</h3>
          <p className="panel-copy">Editable later, but already structured like a real stage editor.</p>
        </div>
        <button type="button" className="ghost-button">
          + Add stage
        </button>
      </div>
      <div className="stage-stack">
        {stages.map((stage) => (
          <StageRowEditor key={stage.key} stage={stage} />
        ))}
      </div>
    </article>
  );
}
