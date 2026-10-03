import Link from "next/link";
import { DocumentsIcon } from "@/components/icons";
import type { DocumentItem } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  ready: "border-green-500/30 text-green-400",
  processing: "border-accent/30 text-accent",
  uploading: "border-accent/30 text-accent",
  failed: "border-red-500/30 text-red-400",
};

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentList({ documents }: { documents: DocumentItem[] }) {
  if (documents.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted">No documents yet.</p>
    );
  }

  return (
    <ul className="space-y-2">
      {documents.map((doc) => (
        <li key={doc.id}>
          <Link
            href={`/documents/${doc.id}`}
            className="grid grid-cols-[20px_1fr_auto] items-center gap-3 rounded-lg border border-border bg-surface px-3 py-2.5 transition-colors duration-150 hover:border-accent/50 hover:bg-surface-raised"
          >
            <DocumentsIcon width={16} height={16} className="text-muted" />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-foreground">
                {doc.title}
              </span>
              <span className="block text-xs text-muted">
                {doc.file_type.toUpperCase()} ·{" "}
                {formatSize(doc.file_size_bytes)} ·{" "}
                {new Date(doc.created_at).toLocaleDateString()}
              </span>
            </span>
            <span
              className={`rounded-md border px-2 py-0.5 text-xs capitalize ${STATUS_STYLES[doc.status] ?? "border-border text-muted"}`}
            >
              {doc.status}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
