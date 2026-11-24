import { PromptPreview } from "./PromptPreview";

type PromptEditorProps = {
  prompt: string;
};

export function PromptEditor({ prompt }: PromptEditorProps) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h3>Prompt</h3>
          <p className="panel-copy">This prompt is scoped to the selected journey only.</p>
        </div>
        <button type="button" className="ghost-button">
          Prompt preview
        </button>
      </div>
      <textarea className="prompt-editor" defaultValue={prompt} rows={12} />
      <PromptPreview prompt={prompt} />
    </article>
  );
}
