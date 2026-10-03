import { CloseIcon, ExternalLinkIcon, DownloadIcon } from "@/components/icons";
import type { Source } from "@/lib/mockKnowledge";

interface SourcePreviewProps {
  source: Source | null;
  onClose?: () => void;
}

/**
 * Contextual detail for whichever source is currently selected. Used
 * both as one section of the desktop right rail (see DashboardShell)
 * and, with `onClose` supplied, as the standalone content of the
 * mobile drawer.
 */
export function SourcePreview({ source, onClose }: SourcePreviewProps) {
  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="text-sm font-semibold text-foreground">Source preview</h2>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close source preview"
            className="rounded-md p-1 text-muted transition-colors duration-150 hover:bg-surface-raised hover:text-foreground"
          >
            <CloseIcon />
          </button>
        )}
      </div>

      {source ? (
        <div key={source.id} className="animate-fade-in px-5 py-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold text-foreground">{source.title}</h3>
              <p className="mt-0.5 text-xs text-muted">Page {source.page} of 42</p>
            </div>
            {/* Not wired up yet — present for information architecture
                completeness, same convention as the answer's feedback row. */}
            <div className="flex shrink-0 items-center gap-1">
              <button type="button" disabled aria-label="Open source" className="flex h-7 w-7 cursor-default items-center justify-center rounded-md text-muted/50">
                <ExternalLinkIcon width={14} height={14} />
              </button>
              <button type="button" disabled aria-label="Download source" className="flex h-7 w-7 cursor-default items-center justify-center rounded-md text-muted/50">
                <DownloadIcon width={14} height={14} />
              </button>
            </div>
          </div>

          {/* A warm "paper" swatch — the cited page rendered as an actual
              page, not another dark panel, so the source preview reads
              as a real document rather than more chrome. */}
          <div className="mt-4 rounded-lg bg-[#ddd9ce] p-4">
            <p className="text-xs font-semibold tracking-wide text-[#4a463d] uppercase">{source.previewHeading}</p>
            <p className="mt-2 text-sm leading-relaxed text-[#272622]">{source.snippet}</p>
            <p className="mt-3 text-xs font-semibold tracking-wide text-[#4a463d] uppercase">Key changes</p>
            <ul className="mt-1.5 space-y-1 text-sm leading-relaxed text-[#272622]">
              {source.previewPoints.map((point) => (
                <li key={point} className="flex gap-1.5">
                  <span aria-hidden="true">•</span>
                  {point}
                </li>
              ))}
            </ul>
          </div>

          <div className="mt-4 flex items-center justify-between text-xs">
            <span className="font-medium tracking-wide text-muted uppercase">Relevance</span>
            <span className="font-semibold text-accent">{source.relevance}%</span>
          </div>
          <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-surface-raised">
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out"
              style={{ width: `${source.relevance}%` }}
            />
          </div>

          <div className="mt-4 flex flex-wrap gap-1.5">
            {source.tags.map((tag) => (
              <span key={tag} className="rounded-full border border-border px-2 py-0.5 text-xs text-muted">
                {tag}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div className="px-5 py-8 text-center text-sm text-muted">Select a source to preview it here.</div>
      )}
    </div>
  );
}
