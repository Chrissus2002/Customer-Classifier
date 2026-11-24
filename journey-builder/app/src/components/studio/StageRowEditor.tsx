import type { StageDefinition } from "../../data/studio";

type StageRowEditorProps = {
  stage: StageDefinition;
};

export function StageRowEditor({ stage }: StageRowEditorProps) {
  return (
    <div className="stage-card">
      <strong>{stage.label}</strong>
      <div className="cell-note">{stage.key}</div>
      <p>{stage.description}</p>
    </div>
  );
}
