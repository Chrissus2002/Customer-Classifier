import { Link } from "react-router-dom";
import type { JourneyStudioRecord } from "../../data/studio";
import { routes } from "../../routes";

type EvalSummaryPanelProps = {
  record: JourneyStudioRecord;
};

export function EvalSummaryPanel({ record }: EvalSummaryPanelProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Draft evaluation</h3>
          <p className="panel-copy">Review the current draft against recent sample conversations.</p>
        </div>
        <div className="panel-actions">
          <button type="button" className="ghost-button">
            Test draft
          </button>
          <button type="button" className="primary-button">
            Activate draft
          </button>
        </div>
      </div>
      <div className="eval-metrics">
        <div className="eval-metric">
          <span>Agreement</span>
          <strong>{record.evalMetrics.agreement}</strong>
          <small>{record.evalMetrics.agreementDelta}</small>
        </div>
        <div className="eval-metric">
          <span>Changed labels</span>
          <strong>{record.evalMetrics.changedLabels}</strong>
          <small>{record.evalMetrics.changedLabelsNote}</small>
        </div>
        <div className="eval-metric">
          <span>Confidence avg</span>
          <strong>{record.evalMetrics.confidenceAvg}</strong>
          <small>{record.evalMetrics.confidenceDelta}</small>
        </div>
      </div>
      <table className="data-table compact-table">
        <thead>
          <tr>
            <th>Contact</th>
            <th>Expected</th>
            <th>Active</th>
            <th>Draft</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {record.evalRows.map((row) => (
            <tr key={row.contactId}>
              <td>
                <Link className="text-link" to={routes.contactInspector(row.contactId)}>
                  {row.contact}
                </Link>
              </td>
              <td>{row.expected}</td>
              <td>{row.active}</td>
              <td>{row.draft}</td>
              <td>{row.why}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  );
}
