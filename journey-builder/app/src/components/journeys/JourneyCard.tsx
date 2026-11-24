import { Link } from "react-router-dom";
import type { JourneySummary } from "../../data/journeys";
import { routes } from "../../routes";

type JourneyCardProps = {
  journey: JourneySummary;
};

export function JourneyCard({ journey }: JourneyCardProps) {
  return (
    <article className="journey-card journey-card--row">
      <div className="journey-card-main">
        <div className="journey-card-heading">
          <span className="eyebrow">{journey.journeyKey}</span>
          <h3>{journey.name}</h3>
          <p className="panel-copy">{journey.note}</p>
        </div>

        <dl className="journey-stats journey-stats--row">
          <div>
            <dt>Active</dt>
            <dd>{journey.activeVersion}</dd>
          </div>
          <div>
            <dt>Draft</dt>
            <dd>{journey.draftStatus}</dd>
          </div>
          <div>
            <dt>Enrolled</dt>
            <dd>{journey.enrolled}</dd>
          </div>
          <div>
            <dt>Stale</dt>
            <dd>{journey.staleCount}</dd>
          </div>
          <div>
            <dt>Eval</dt>
            <dd>{journey.lastEval}</dd>
          </div>
          <div>
            <dt>Updated</dt>
            <dd>{journey.lastUpdated}</dd>
          </div>
        </dl>
      </div>

      <div className="journey-card-actions journey-card-actions--stacked">
        <Link className="primary-button button-link" to={routes.journeyStudio(journey.journeyKey)}>
          Open Studio
        </Link>
        <Link className="text-link" to={routes.contactInspector(journey.sampleContactId)}>
          Inspect sample contact
        </Link>
      </div>
    </article>
  );
}
