import { SourceList } from "@/components/dashboard/SourceList";
import { ThumbUpIcon, ThumbDownIcon, CommentIcon, ChevronDownIcon } from "@/components/icons";
import type { AnswerData } from "@/lib/mockKnowledge";

interface AnswerPanelProps {
  answer: AnswerData;
  isThinking: boolean;
  selectedSourceId: string | null;
  onSelectSource: (id: string) => void;
}

/** The current answer — question echo, Nexus answer, key points, and cited sources. */
export function AnswerPanel({ answer, isThinking, selectedSourceId, onSelectSource }: AnswerPanelProps) {
  if (isThinking) {
    return <ThinkingState />;
  }

  return (
    <div key={answer.question} className="animate-fade-in">
      <p className="text-sm font-medium text-muted">{answer.question}</p>

      <div className="mt-3">
        <p className="text-xs font-semibold tracking-wide text-accent uppercase">Nexus answer</p>
        <p className="mt-2 text-lg leading-relaxed text-foreground">{answer.answer}</p>
      </div>

      <div className="mt-6">
        <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Key points</h3>
        <ul className="mt-2 space-y-1.5">
          {answer.keyPoints.map((point) => (
            <li key={point} className="flex gap-2 text-sm text-foreground">
              <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent" />
              {point}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-6">
        <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Sources</h3>
        <div className="mt-2">
          <SourceList sources={answer.sources} selectedSourceId={selectedSourceId} onSelectSource={onSelectSource} />
        </div>
        {answer.sources.length > 1 && (
          <button
            type="button"
            disabled
            className="mt-3 flex w-full cursor-default items-center justify-center gap-1 text-xs text-accent/70"
          >
            Show all {answer.sources.length} sources
            <ChevronDownIcon width={12} height={12} />
          </button>
        )}
      </div>

      {/* Not wired up yet — present for information architecture
          completeness, same "visually present, clearly inert" convention
          used for the sidebar's unbuilt sections. */}
      <div className="mt-6 flex items-center gap-1 border-t border-border pt-4">
        <button type="button" disabled aria-label="Helpful answer" className="flex h-7 w-7 cursor-default items-center justify-center rounded-md text-muted/50">
          <ThumbUpIcon width={14} height={14} />
        </button>
        <button type="button" disabled aria-label="Unhelpful answer" className="flex h-7 w-7 cursor-default items-center justify-center rounded-md text-muted/50">
          <ThumbDownIcon width={14} height={14} />
        </button>
        <button type="button" disabled aria-label="Comment" className="flex h-7 w-7 cursor-default items-center justify-center rounded-md text-muted/50">
          <CommentIcon width={14} height={14} />
        </button>
      </div>
    </div>
  );
}

function ThinkingState() {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted">
      <span className="flex gap-1">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.2s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.1s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent" />
      </span>
      Thinking…
    </div>
  );
}
