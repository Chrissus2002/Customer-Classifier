import type { ConversationLine } from "../../data/inspector";

type ConversationExcerptProps = {
  conversation: ConversationLine[];
};

export function ConversationExcerpt({ conversation }: ConversationExcerptProps) {
  return (
    <article className="panel conversation-panel">
      <div className="panel-header">
        <div>
          <h3>Conversation</h3>
          <p className="panel-copy">Keep the transcript primary so the classification context reads from evidence, not from charts.</p>
        </div>
      </div>
      <div className="conversation-thread">
        {conversation.map((line) => {
          const speakerClass = line.speaker.toLowerCase();
          return (
            <div key={line.id} className={`conversation-line conversation-line--${speakerClass}`}>
              <span className="conversation-speaker">{line.speaker}</span>
              <p className="conversation-bubble">{line.text}</p>
            </div>
          );
        })}
      </div>
    </article>
  );
}
