import { Link } from "react-router-dom";
import { routingPreview, routingRules } from "../../data/routing";
import { routes } from "../../routes";

export function RoutingSummaryPanel() {
  return (
    <article className="panel summary-panel">
      <div className="panel-header">
        <div>
          <h3>Routing</h3>
          <p className="panel-copy">Current rules for assigning contacts to journeys.</p>
        </div>
      </div>

      <table className="data-table compact-table">
        <thead>
          <tr>
            <th>#</th>
            <th>If</th>
            <th>Then</th>
          </tr>
        </thead>
        <tbody>
          {routingRules.map((rule) => (
            <tr key={rule.id}>
              <td>{rule.order}</td>
              <td>{rule.when}</td>
              <td>{rule.then}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="preview-banner">
        <strong>37 contacts would change journeys</strong>
        <span>Most changes come from the updated wholesale classifier rule.</span>
      </div>

      <div className="stack">
        {routingPreview.slice(0, 2).map((row) => (
          <div key={row.contactId} className="preview-card">
            <strong>{row.contact}</strong>
            <span>
              {row.oldJourney} -&gt; {row.newJourney}
            </span>
            <p>{row.why}</p>
            <Link className="text-link" to={routes.contactInspector(row.contactId)}>
              Inspect contact
            </Link>
          </div>
        ))}
      </div>
    </article>
  );
}
