"use client";

import { useState } from "react";
import Link from "next/link";
import { SparkleIcon } from "@/components/icons";
import { ChatPanel } from "@/components/app/ChatPanel";
import { ConversationList } from "@/components/app/ConversationList";
import { DocumentUploader } from "@/components/app/DocumentUploader";
import { DocumentList } from "@/components/app/DocumentList";
import { citationHref, pageLabel, type Citation } from "@/lib/api";
import { useWorkspaceDocuments } from "@/lib/useWorkspace";

const SUGGESTIONS = ["Summarize my documents", "What are the key points?", "List any dates or deadlines mentioned"];

export function AskView({ initialConversationId }: { initialConversationId?: string }) {
  const { workspaceId, documents, loading, error, refreshDocuments } = useWorkspaceDocuments();
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId ?? null);
  const [selected, setSelected] = useState<Citation | null>(null);
  const [listVersion, setListVersion] = useState(0);

  const readyCount = documents.filter((d) => d.status === "ready").length;

  function openConversation(id: string | null) {
    setConversationId(id);
    setSelected(null);
    // Keep the open conversation in the URL so a reload or shared link reopens it.
    window.history.replaceState(null, "", id ? `/dashboard?c=${id}` : "/dashboard");
  }

  if (loading) return <CenteredMessage text="Loading your workspace…" />;
  if (error || !workspaceId) return <CenteredMessage text={error ?? "Could not load your workspace."} error />;

  const conversationList = (
    <ConversationList
      workspaceId={workspaceId}
      activeId={conversationId}
      onSelect={openConversation}
      refreshKey={listVersion}
    />
  );

  return (
    <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[240px_minmax(0,1fr)_320px]">
      <nav className="hidden flex-col overflow-y-auto border-r border-border bg-surface px-3 py-4 xl:flex" aria-label="Chat history">
        <h2 className="mb-3 px-1 text-xs font-semibold tracking-wide text-muted uppercase">Conversations</h2>
        {conversationList}
      </nav>

      <main className="flex min-h-0 flex-col">
        <div className="border-b border-border px-6 py-3 lg:px-10">
          <h1 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <SparkleIcon width={14} height={14} className="text-accent" />
            Ask Nexus
          </h1>
        </div>
        <ChatPanel
          workspaceId={workspaceId}
          conversationId={conversationId}
          onConversationChange={openConversation}
          onActivity={() => setListVersion((v) => v + 1)}
          selected={selected}
          onSelect={setSelected}
          inputLabel="Ask Nexus"
          placeholder={readyCount ? "Ask anything about your documents…" : "Upload a document first →"}
          disabled={!readyCount}
          suggestions={SUGGESTIONS}
          empty={
            <div className="rounded-xl border border-border bg-surface px-6 py-10 text-center">
              {readyCount ? (
                <p className="text-sm text-muted">
                  {readyCount} document{readyCount === 1 ? "" : "s"} ready. Ask a question below — answers come from
                  your documents, with sources. Follow-up questions remember the conversation.
                </p>
              ) : (
                <>
                  <p className="text-sm text-foreground">You haven&apos;t uploaded any documents yet.</p>
                  <p className="mt-1 text-sm text-muted">Upload one on the right (or on the Documents page) to start asking.</p>
                </>
              )}
            </div>
          }
        />
      </main>

      <aside className="hidden flex-col divide-y divide-border overflow-y-auto border-l border-border bg-surface lg:flex">
        <section className="px-5 py-4 xl:hidden">
          <h2 className="mb-3 text-sm font-semibold text-foreground">Conversations</h2>
          {conversationList}
        </section>

        <section className="px-5 py-4">
          <h2 className="text-sm font-semibold text-foreground">Source preview</h2>
          {selected ? (
            <div className="mt-3">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate text-sm font-medium text-foreground">{selected.document_title}</p>
                <Link href={citationHref(selected)} className="shrink-0 text-xs text-accent hover:text-accent-hover">
                  {pageLabel(selected) ? `Open ${pageLabel(selected)}` : "Open"} ↗
                </Link>
              </div>
              <p className="mt-3 rounded-lg bg-[#ddd9ce] p-4 text-sm leading-relaxed whitespace-pre-wrap text-[#272622]">
                {selected.excerpt}
                {selected.excerpt.length >= 300 ? "…" : ""}
              </p>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted">Sources for an answer show up here.</p>
          )}
        </section>

        <section className="px-5 py-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground">Your documents</h2>
            <Link href="/documents" className="text-xs text-accent hover:text-accent-hover">
              Manage
            </Link>
          </div>
          <div className="mt-3">
            <DocumentUploader workspaceId={workspaceId} onUploaded={refreshDocuments} compact />
          </div>
          <div className="mt-3">
            <DocumentList documents={documents.slice(0, 6)} />
          </div>
        </section>
      </aside>
    </div>
  );
}

export function CenteredMessage({ text, error = false }: { text: string; error?: boolean }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <p className={error ? "text-sm text-red-400" : "text-sm text-muted"}>{text}</p>
    </div>
  );
}
