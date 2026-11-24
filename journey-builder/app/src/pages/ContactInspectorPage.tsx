import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { NotFoundState } from "../components/NotFoundState";
import { ConversationExcerpt } from "../components/inspector/ConversationExcerpt";
import { JourneyStatePanel } from "../components/inspector/JourneyStatePanel";
import { RoutingExplanationPanel } from "../components/inspector/RoutingExplanationPanel";
import { StageStatePanel } from "../components/inspector/StageStatePanel";
import { TraitStatePanel } from "../components/inspector/TraitStatePanel";
import { getContactInspectorRecord } from "../data/inspector";
import { routes } from "../routes";

export function ContactInspectorPage() {
  const { contactId = "" } = useParams();
  const record = getContactInspectorRecord(contactId);
  const [showInsights, setShowInsights] = useState(true);

  if (!record) {
    return (
      <AppShell
        eyebrow="Contact Inspector"
        title="Contact not found"
        description="The requested contact could not be found."
        breadcrumbs={[
          { label: "Journeys", to: routes.journeys },
          { label: "Missing contact" },
        ]}
      >
        <NotFoundState
          title="Unknown contact"
          description="Use a known mock `contactId` like `contact-alma`, `contact-carlos`, or `contact-julia`."
        />
      </AppShell>
    );
  }

  return (
    <AppShell
      eyebrow="Contact Inspector"
      title={record.name}
      description="Read the conversation first, then open only the routing and stage detail you need."
      breadcrumbs={[
        { label: "Journeys", to: routes.journeys },
        { label: record.journeyLabel, to: routes.journeyStudio(record.journeyKey) },
        { label: record.name },
      ]}
      actions={
        <>
          <button type="button" className="ghost-button" onClick={() => setShowInsights((value) => !value)}>
            {showInsights ? "Hide insights" : "Show insights"}
          </button>
          <Link className="ghost-button button-link" to={routes.journeyStudio(record.journeyKey)}>
            Back to Studio
          </Link>
        </>
      }
    >
      <div className={`inspector-shell${showInsights ? " inspector-shell--with-rail" : ""}`}>
        <section className="inspector-main stack">
          <article className="panel subtle-panel inspector-summary">
            <dl className="journey-stats journey-stats--wide">
              <div>
                <dt>Journey</dt>
                <dd>{record.journeyLabel}</dd>
              </div>
              <div>
                <dt>Current stage</dt>
                <dd>{record.stageLabel}</dd>
              </div>
              <div>
                <dt>Last inbound</dt>
                <dd>{record.lastInbound}</dd>
              </div>
            </dl>
          </article>
          <ConversationExcerpt conversation={record.conversation} />
        </section>

        {showInsights ? (
          <aside className="inspector-rail">
            <details className="insight-section" open>
              <summary className="insight-summary">
                <span>Resolved traits</span>
                <small>{record.traits.length} attributes</small>
              </summary>
              <TraitStatePanel traits={record.traits} />
            </details>

            <details className="insight-section" open>
              <summary className="insight-summary">
                <span>Routing</span>
                <small>{record.routingConfigVersion}</small>
              </summary>
              <RoutingExplanationPanel
                rule={record.routingRule}
                configVersion={record.routingConfigVersion}
                reason={record.routingReason}
              />
            </details>

            <details className="insight-section">
              <summary className="insight-summary">
                <span>Journey</span>
                <small>{record.journeyLabel}</small>
              </summary>
              <JourneyStatePanel
                journeyLabel={record.journeyLabel}
                lastActivity={record.lastActivity}
                lastInbound={record.lastInbound}
              />
            </details>

            <details className="insight-section" open>
              <summary className="insight-summary">
                <span>Stage result</span>
                <small>{record.stageState}</small>
              </summary>
              <StageStatePanel
                stageKey={record.stageKey}
                stageLabel={record.stageLabel}
                stageState={record.stageState}
                confidence={record.confidence}
                classifiedAt={record.classifiedAt}
              />
            </details>
          </aside>
        ) : null}
      </div>
    </AppShell>
  );
}
