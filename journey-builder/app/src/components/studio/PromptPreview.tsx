type PromptPreviewProps = {
  prompt: string;
};

export function PromptPreview({ prompt }: PromptPreviewProps) {
  return (
    <div className="preview-card">
      <strong>Prompt preview</strong>
      <p>{prompt.split("\n").slice(0, 2).join(" ")}</p>
    </div>
  );
}
