import { MetricCard } from "../MetricCard";
import { traitActivity, traitClassifierSummaries, traitSummaries } from "../../data/traits";

export function TraitsSummaryPanel() {
  return (
    <article className="panel summary-panel">
      <div className="panel-header">
        <div>
          <h3>Traits</h3>
          <p className="panel-copy">Coverage and resolver status across the current workspace.</p>
        </div>
      </div>

      <div className="summary-metrics">
        <MetricCard label="Traits" value="3" detail="Tracked across active contacts" />
        <MetricCard label="Resolvers" value="3" detail="Classifier, rule, and imported" />
      </div>

      <table className="data-table compact-table">
        <thead>
          <tr>
            <th>Trait</th>
            <th>Resolver</th>
            <th>Coverage</th>
          </tr>
        </thead>
        <tbody>
          {traitSummaries.map((trait) => (
            <tr key={trait.key}>
              <td>
                <strong>{trait.label}</strong>
                <div className="cell-note">{trait.values}</div>
              </td>
              <td>{trait.resolver}</td>
              <td>{trait.coverage}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="preview-card">
        <strong>{traitClassifierSummaries[0].name}</strong>
        <span>
          {traitClassifierSummaries[0].trait} · {traitClassifierSummaries[0].version} · {traitClassifierSummaries[0].status}
        </span>
        <p>{traitClassifierSummaries[0].note}</p>
      </div>

      <ul className="bullet-list">
        {traitActivity.slice(0, 2).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </article>
  );
}
