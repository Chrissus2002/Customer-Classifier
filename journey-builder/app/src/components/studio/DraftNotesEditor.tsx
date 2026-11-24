type DraftNotesEditorProps = {
  notes: string;
};

export function DraftNotesEditor({ notes }: DraftNotesEditorProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Draft notes</h3>
          <p className="panel-copy">Operator-facing note for why this draft exists.</p>
        </div>
      </div>
      <textarea className="notes-editor" defaultValue={notes} rows={6} />
    </article>
  );
}
