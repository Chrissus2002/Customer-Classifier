import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { NotFoundState } from "../components/NotFoundState";
import { DraftNotesEditor } from "../components/studio/DraftNotesEditor";
import { EvalSummaryPanel } from "../components/studio/EvalSummaryPanel";
import { JourneyHeader } from "../components/studio/JourneyHeader";
import { PromptEditor } from "../components/studio/PromptEditor";
import { StageListEditor } from "../components/studio/StageListEditor";
import { VersionHistoryList } from "../components/studio/VersionHistoryList";
import { getJourneyStudioRecord } from "../data/studio";
import { routes } from "../routes";

type StudioTab = "prompt" | "stages" | "review";

export function JourneyStudioPage() {
  const { journeyKey = "" } = useParams();
  const record = getJourneyStudioRecord(journeyKey);
  const [activeTab, setActiveTab] = useState<StudioTab>("prompt");
  const [showContext, setShowContext] = useState(false);

  if (!record) {
    return (
      <AppShell
        eyebrow="Journey Studio"
        title="Journey not found"
        description="The requested journey could not be found."
        breadcrumbs={[
          { label: "Journeys", to: routes.journeys },
          { label: "Missing journey" },
        ]}
      >
        <NotFoundState
          title="Unknown journey"
          description="Use a known mock `journeyKey` like `retail_buyers`, `wholesale_buyers`, or `vip_recovery`."
        />
      </AppShell>
    );
  }

  return (
    <AppShell
      eyebrow="Journey Studio"
      title={record.journeyLabel}
      description="Work on one journey at a time, with the draft front and center and the secondary context tucked away."
      breadcrumbs={[
        { label: "Journeys", to: routes.journeys },
        { label: record.journeyLabel },
      ]}
      actions={
        <>
          <button type="button" className="ghost-button" onClick={() => setShowContext((value) => !value)}>
            {showContext ? "Hide context" : "Show context"}
          </button>
          <button type="button" className="primary-button">
            Save Draft
          </button>
        </>
      }
    >
      <div className={`studio-shell${showContext ? " studio-shell--with-context" : ""}`}>
        <section className="studio-primary stack">
          <JourneyHeader record={record} />

          <div className="studio-tabs" role="tablist" aria-label="Journey studio sections">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "prompt"}
              className={activeTab === "prompt" ? "studio-tab is-active" : "studio-tab"}
              onClick={() => setActiveTab("prompt")}
            >
              Prompt
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "stages"}
              className={activeTab === "stages" ? "studio-tab is-active" : "studio-tab"}
              onClick={() => setActiveTab("stages")}
            >
              Stages
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "review"}
              className={activeTab === "review" ? "studio-tab is-active" : "studio-tab"}
              onClick={() => setActiveTab("review")}
            >
              Review
            </button>
          </div>

          {activeTab === "prompt" ? (
            <div className="stack">
              <PromptEditor prompt={record.prompt} />
              <DraftNotesEditor notes={record.draftNotes} />
            </div>
          ) : null}

          {activeTab === "stages" ? <StageListEditor stages={record.stages} /> : null}

          {activeTab === "review" ? (
            <div className="stack">
              <EvalSummaryPanel record={record} />
              <article className="panel subtle-panel">
                <div className="panel-header">
                  <div>
                    <h3>Review focus</h3>
                    <p className="panel-copy">Open a contact, inspect the conversation, and decide whether the draft behaves the way you expect.</p>
                  </div>
                </div>
                <Link className="text-link" to={routes.contactInspector(record.evalRows[0]?.contactId ?? "contact-alma")}>
                  Open sample contact
                </Link>
              </article>
            </div>
          ) : null}
        </section>

        {showContext ? (
          <aside className="studio-context stack">
            <VersionHistoryList entries={record.versionHistory} />
            <article className="panel subtle-panel">
              <div className="panel-header">
                <div>
                  <h3>Current draft state</h3>
                  <p className="panel-copy">Keep the working context nearby without letting it dominate the screen.</p>
                </div>
              </div>
              <dl className="journey-stats journey-stats--single">
                <div>
                  <dt>Active version</dt>
                  <dd>{record.activeVersion}</dd>
                </div>
                <div>
                  <dt>Draft version</dt>
                  <dd>{record.draftVersion}</dd>
                </div>
                <div>
                  <dt>Unsaved changes</dt>
                  <dd>{record.unsavedChanges}</dd>
                </div>
              </dl>
            </article>
          </aside>
        ) : null}
      </div>
    </AppShell>
  );
}
