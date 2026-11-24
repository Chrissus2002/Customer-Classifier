import { AppShell } from "../components/AppShell";
import { JourneyCard } from "../components/journeys/JourneyCard";
import { RecentChangesPanel } from "../components/journeys/RecentChangesPanel";
import { RoutingSummaryPanel } from "../components/routing/RoutingSummaryPanel";
import { TraitsSummaryPanel } from "../components/traits/TraitsSummaryPanel";
import { journeySummaries, recentJourneyChanges } from "../data/journeys";

export function JourneyListPage() {
  return (
    <AppShell
      eyebrow="Workspace"
      title="Journeys"
      description="Open journeys, review live drafts, and dip into automation context only when you need it."
    >
      <div className="page-stack">
        <section className="journey-list-shell stack">
          <div className="section-intro">
            <div>
              <span className="eyebrow">Current workspace</span>
              <h2>One place to manage active journeys</h2>
            </div>
            <p className="panel-copy">Pick a journey, go deep in Studio, and keep the automation plumbing tucked away until it matters.</p>
          </div>

          <div className="journey-list">
            {journeySummaries.map((journey) => (
              <JourneyCard key={journey.journeyKey} journey={journey} />
            ))}
          </div>
        </section>

        <details className="automation-disclosure">
          <summary className="disclosure-summary">
            <div>
              <strong>Automation context</strong>
              <span>Traits and routing stay available, but out of the way.</span>
            </div>
          </summary>
          <div className="disclosure-body automation-grid">
            <TraitsSummaryPanel />
            <RoutingSummaryPanel />
          </div>
        </details>

        <RecentChangesPanel changes={recentJourneyChanges} />
      </div>
    </AppShell>
  );
}
