import Link from "next/link";
import { DocumentsIcon } from "@/components/icons";
import { citationHref, pageLabel, type Citation } from "@/lib/api";

export interface Turn {
  question: string;
  answer?: string;
  citations?: Citation[];
  error?: string;
}

interface AnswerTurnProps {
  turn: Turn;
  selected: Citation | null;
  onSelect: (c: Citation) => void;
  showOpenLinks?: boolean;
}

/** One question with its pending / error / answered state and cited sources. */
export function AnswerTurn({ turn, selected, onSelect, showOpenLinks = true }: AnswerTurnProps) {
  return (
    <div className="animate-fade-in">
      <p className="text-sm font-medium text-muted">{turn.question}</p>

      {!turn.answer && !turn.error && (
        <div role="status" className="mt-3 flex items-center gap-2 text-sm text-muted">
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.2s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.1s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent" />
          </span>
          Thinking…
        </div>
      )}

      {turn.error && (
        <p className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm break-words text-red-400">
          {turn.error}
        </p>
      )}

      {turn.answer && (
        <>
          <p className="mt-3 text-xs font-semibold tracking-wide text-accent uppercase">Nexus answer</p>
          <p className="mt-2 leading-relaxed whitespace-pre-wrap text-foreground">{turn.answer}</p>

          {turn.citations && turn.citations.length > 0 && (
            <div className="mt-5">
              <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Sources</h3>
              <div className="mt-2 space-y-2">
                {turn.citations.map((c) => {
                  const isSelected = selected?.chunk_id === c.chunk_id;
                  return (
                    <div
                      key={c.chunk_id}
                      className={[
                        "grid grid-cols-[1fr_auto] items-start gap-2 rounded-lg border transition-colors duration-200",
                        isSelected ? "border-accent/50 bg-accent-soft" : "border-border bg-surface hover:border-zinc-600",
                      ].join(" ")}
                    >
                      <button
                        type="button"
                        onClick={() => onSelect(c)}
                        aria-pressed={isSelected}
                        className="grid min-w-0 grid-cols-[20px_1fr] items-start gap-3 px-3 py-2.5 text-left"
                      >
                        <DocumentsIcon
                          width={16}
                          height={16}
                          className={isSelected ? "mt-0.5 text-accent" : "mt-0.5 text-muted"}
                        />
                        <span className="min-w-0">
                          <span className="flex items-baseline gap-2">
                            <span className="truncate text-sm font-medium text-foreground">{c.document_title}</span>
                            {pageLabel(c) && (
                              <span className="shrink-0 rounded border border-accent/30 px-1.5 text-[11px] text-accent">
                                {pageLabel(c)}
                              </span>
                            )}
                          </span>
                          <span className="line-clamp-2 block text-xs text-muted">{c.excerpt}</span>
                        </span>
                      </button>
                      {showOpenLinks && (
                        <Link
                          href={citationHref(c)}
                          className="px-3 py-2.5 text-xs whitespace-nowrap text-accent hover:text-accent-hover"
                        >
                          Open
                        </Link>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
