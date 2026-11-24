import type { ResolvedTrait } from "../../data/inspector";

type TraitStatePanelProps = {
  traits: ResolvedTrait[];
};

export function TraitStatePanel({ traits }: TraitStatePanelProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Resolved traits</h3>
          <p className="panel-copy">Current trait values, source, and evidence for this contact.</p>
        </div>
      </div>
      <div className="stack">
        {traits.map((trait) => (
          <div key={trait.key} className="preview-card">
            <strong>
              {trait.key} = {trait.value}
            </strong>
            <span>
              confidence {trait.confidence} · source {trait.source}
            </span>
            <p>{trait.reason}</p>
          </div>
        ))}
      </div>
    </article>
  );
}
