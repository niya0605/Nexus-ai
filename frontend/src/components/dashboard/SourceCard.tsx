import { DocumentsIcon } from "@/components/icons";

interface SourceCardProps {
  title: string;
  page: number;
  updatedLabel: string;
  selected?: boolean;
  onSelect?: () => void;
}

/**
 * One citation row — "Q3 Roadmap v2.1 / Updated 2 days ago / Page 14" —
 * used in the answer's source list. Selecting one drives the right-hand
 * source preview panel; this is the component that makes that
 * connection visible.
 */
export function SourceCard({ title, page, updatedLabel, selected, onSelect }: SourceCardProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={[
        "group grid w-full grid-cols-[20px_1fr_auto] items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors duration-200",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        selected
          ? "border-accent/50 bg-accent-soft"
          : "border-border bg-surface hover:border-zinc-600 hover:bg-surface-raised",
      ].join(" ")}
    >
      <DocumentsIcon width={16} height={16} className={selected ? "text-accent" : "text-muted"} />
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-foreground">{title}</span>
        <span className="block text-xs text-muted">{updatedLabel}</span>
      </span>
      <span className="shrink-0 rounded-md border border-accent/20 px-2 py-1 text-xs text-accent">Page {page}</span>
    </button>
  );
}
