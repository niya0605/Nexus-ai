"use client";

import { useEffect, useState } from "react";
import { deleteConversation, listConversations, type ConversationSummary } from "@/lib/api";

interface ConversationListProps {
  workspaceId: string;
  /** Only this document's conversations; otherwise every conversation in the workspace. */
  documentId?: string;
  activeId: string | null;
  onSelect: (id: string | null) => void;
  /** Change this value to reload the list (e.g. after a question is answered). */
  refreshKey: number;
  /** Called once with the most recent conversation after the first load. */
  onFirstLoad?: (conversations: ConversationSummary[]) => void;
  compact?: boolean;
}

function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function ConversationList({
  workspaceId,
  documentId,
  activeId,
  onSelect,
  refreshKey,
  onFirstLoad,
  compact = false,
}: ConversationListProps) {
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [firstLoadDone, setFirstLoadDone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listConversations(workspaceId, documentId)
      .then((list) => {
        if (cancelled) return;
        setConversations(list);
        setError(null);
        if (!firstLoadDone) {
          setFirstLoadDone(true);
          onFirstLoad?.(list);
        }
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not load conversations."));
    return () => {
      cancelled = true;
    };
    // Reload only when the scope or refreshKey changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, documentId, refreshKey]);

  async function remove(conversation: ConversationSummary) {
    if (!window.confirm(`Delete "${conversation.title}"? This can't be undone.`)) return;
    try {
      await deleteConversation(workspaceId, conversation.id);
      setConversations((prev) => prev?.filter((c) => c.id !== conversation.id) ?? null);
      if (conversation.id === activeId) onSelect(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the conversation.");
    }
  }

  return (
    <div className="flex min-h-0 flex-col">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className="mb-3 flex h-9 items-center justify-center gap-1.5 rounded-lg border border-accent/30 text-sm text-foreground transition-colors duration-150 hover:border-accent hover:bg-accent-soft"
      >
        + New chat
      </button>

      {error && <p className="mb-2 text-xs text-red-400">{error}</p>}
      {conversations === null && !error && <p className="text-xs text-muted">Loading…</p>}
      {conversations?.length === 0 && (
        <p className="text-xs text-muted">
          {documentId ? "No conversations about this document yet." : "Your conversations will appear here."}
        </p>
      )}

      <ul className={`space-y-1 overflow-y-auto ${compact ? "max-h-40" : ""}`} aria-label="Conversations">
        {conversations?.map((c) => {
          const active = c.id === activeId;
          return (
            <li key={c.id} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                aria-current={active ? "true" : undefined}
                className={[
                  "w-full rounded-lg px-3 py-2 pr-8 text-left transition-colors duration-150",
                  active ? "bg-accent-soft text-foreground" : "text-muted hover:bg-surface-raised hover:text-foreground",
                ].join(" ")}
              >
                <span className="block truncate text-sm">{c.title}</span>
                <span className="block text-[11px] text-muted">
                  {timeAgo(c.updated_at)} · {Math.ceil(c.message_count / 2)} question{c.message_count > 2 ? "s" : ""}
                </span>
              </button>
              <button
                type="button"
                onClick={() => remove(c)}
                aria-label={`Delete conversation ${c.title}`}
                className="absolute top-2 right-1.5 hidden h-6 w-6 items-center justify-center rounded text-muted hover:bg-red-500/10 hover:text-red-400 group-hover:flex group-focus-within:flex"
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
