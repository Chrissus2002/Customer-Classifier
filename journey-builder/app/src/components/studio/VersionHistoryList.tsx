import type { VersionHistoryEntry } from "../../data/studio";

type VersionHistoryListProps = {
  entries: VersionHistoryEntry[];
};

export function VersionHistoryList({ entries }: VersionHistoryListProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Version history</h3>
          <p className="panel-copy">Journey-local history stays visible while the operator works on the draft.</p>
        </div>
      </div>
      <div className="stack">
        {entries.map((entry) => (
          <div key={`${entry.version}-${entry.changedAt}`} className="preview-card">
            <strong>
              {entry.version} · {entry.status}
            </strong>
            <span>{entry.changedAt}</span>
            <p>{entry.note}</p>
          </div>
        ))}
      </div>
    </article>
  );
}
