const pipelineSteps = [
  {
    key: "conversation",
    title: "Conversation",
    description: "Canonical message history is the raw evidence.",
  },
  {
    key: "traits",
    title: "Chat Traits",
    description: "Resolve chat attributes for the current contact thread.",
  },
  {
    key: "routing",
    title: "Routing",
    description: "Use traits to choose one journey.",
  },
  {
    key: "stage",
    title: "Journey Stage",
    description: "Classify position inside the chosen journey.",
  },
] as const;

type PipelineMode = "journeys" | "studio" | "inspector";

type PipelineRailProps = {
  mode: PipelineMode;
};

function getCurrentIndex(mode: PipelineMode) {
  switch (mode) {
    case "journeys":
      return 2;
    case "studio":
    case "inspector":
      return 3;
    default:
      return 0;
  }
}

export function PipelineRail({ mode }: PipelineRailProps) {
  const currentIndex = getCurrentIndex(mode);

  return (
    <section className="pipeline-card">
      <div className="pipeline-copy">
        <span className="eyebrow">Product logic</span>
        <h2>Conversation -&gt; Traits -&gt; Routing -&gt; Journey Stage</h2>
        <p>
          Start with the provided `chat_id`. Resolve traits from imported data or a Trait Classifier,
          route the contact into one journey, then classify the stage inside that journey.
        </p>
      </div>

      <ol className="pipeline-rail" aria-label="Journey Builder pipeline">
        {pipelineSteps.map((step, index) => {
          const isActive = index <= currentIndex;
          const isCurrent = index === currentIndex;
          return (
            <li
              key={step.key}
              className={[
                "pipeline-step",
                isActive ? "is-active" : "",
                isCurrent ? "is-current" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <span className="pipeline-index">{index + 1}</span>
              <div>
                <strong>{step.title}</strong>
                <p>{step.description}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
