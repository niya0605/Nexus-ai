"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SparkleIcon } from "@/components/icons";
import { CenteredMessage } from "@/components/app/AskView";
import { ChatPanel } from "@/components/app/ChatPanel";
import { ConversationList } from "@/components/app/ConversationList";
import {
  documentFileUrl,
  getDocument,
  getDocumentText,
  getWorkspaceId,
  type Citation,
  type DocumentItem,
} from "@/lib/api";

type Tab = "original" | "text";

export function DocumentViewer({ documentId, initialPage }: { documentId: string; initialPage?: number }) {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [doc, setDoc] = useState<DocumentItem | null>(null);
  const [text, setText] = useState("");
  const [hasOriginal, setHasOriginal] = useState(false);
  const [tab, setTab] = useState<Tab>("text");
  const [page, setPage] = useState<number | undefined>(initialPage);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selected, setSelected] = useState<Citation | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [listVersion, setListVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ws = await getWorkspaceId();
        const [meta, content] = await Promise.all([getDocument(ws, documentId), getDocumentText(ws, documentId)]);
        if (cancelled) return;
        setWorkspaceId(ws);
        setDoc(meta);
        setText(content.text);
        setHasOriginal(content.has_original);
        setTab(content.has_original && meta.file_type === "pdf" ? "original" : "text");
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Could not load this document.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  if (loadError) return <CenteredMessage text={loadError} error />;
  if (!doc || !workspaceId) return <CenteredMessage text="Loading document…" />;

  const canShowOriginal = hasOriginal && doc.file_type !== "docx";

  function jumpTo(c: Citation) {
    setSelected(c);
    if (canShowOriginal && doc?.file_type === "pdf" && c.page_start > 0) {
      setPage(c.page_start);
      setTab("original");
    } else {
      setTab("text");
    }
  }

  return (
    <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_420px]">
      <main className="flex min-h-0 flex-col overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-6 py-3">
          <Link href="/documents" className="text-sm text-muted hover:text-foreground">
            ← Documents
          </Link>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{doc.title}</h1>
          {canShowOriginal && (
            <div className="flex rounded-lg border border-border p-0.5 text-xs">
              {(["original", "text"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTab(t)}
                  className={`rounded-md px-3 py-1 capitalize ${tab === t ? "bg-accent-soft text-foreground" : "text-muted hover:text-foreground"}`}
                >
                  {t === "original" ? "Original" : "Text"}
                </button>
              ))}
            </div>
          )}
          {hasOriginal && (
            <a
              href={documentFileUrl(workspaceId, documentId)}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-accent hover:text-accent-hover"
            >
              Open file ↗
            </a>
          )}
        </div>

        {tab === "original" && canShowOriginal ? (
          <iframe
            // Remount on page change: browsers ignore hash-only src updates on PDF iframes.
            key={page ?? 0}
            title={doc.title}
            src={`${documentFileUrl(workspaceId, documentId)}${page ? `#page=${page}` : ""}`}
            className="min-h-0 flex-1 bg-white"
          />
        ) : (
          <div className="flex-1 overflow-y-auto px-6 py-6">
            {text.trim() ? (
              <pre className="mx-auto max-w-3xl font-sans text-sm leading-relaxed whitespace-pre-wrap text-foreground">
                <Highlighted text={text} highlight={selected?.document_id === documentId ? selected.excerpt : null} />
              </pre>
            ) : (
              <p className="text-sm text-muted">No readable text was found in this document.</p>
            )}
          </div>
        )}
      </main>

      <aside className="flex min-h-0 flex-col border-t border-border bg-surface lg:border-t-0 lg:border-l">
        <div className="border-b border-border px-5 py-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
            <SparkleIcon width={14} height={14} className="text-accent" />
            Ask about this document
          </h2>
          <ConversationList
            workspaceId={workspaceId}
            documentId={documentId}
            activeId={conversationId}
            onSelect={(id) => {
              setConversationId(id);
              setSelected(null);
            }}
            refreshKey={listVersion}
            onFirstLoad={(list) => list[0] && setConversationId(list[0].id)}
            compact
          />
        </div>
        <ChatPanel
          workspaceId={workspaceId}
          documentId={documentId}
          conversationId={conversationId}
          onConversationChange={setConversationId}
          onActivity={() => setListVersion((v) => v + 1)}
          selected={selected}
          onSelect={jumpTo}
          onAutoSelect={setSelected}
          inputLabel="Ask about this document"
          placeholder={doc.status === "ready" ? "Ask a question…" : "This document has no readable text"}
          disabled={doc.status !== "ready"}
          suggestions={["Summarize this document", "What are the key points?"]}
          empty={
            <p className="text-sm text-muted">
              Answers use only this document. Click a source to jump to it.
            </p>
          }
          showOpenLinks={false}
          compact
        />
      </aside>
    </div>
  );
}

function Highlighted({ text, highlight }: { text: string; highlight: string | null }) {
  const needle = highlight?.slice(0, 120).trim();
  const index = needle ? text.indexOf(needle) : -1;
  if (!needle || index === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, index)}
      <mark
        ref={(el) => el?.scrollIntoView({ block: "center", behavior: "smooth" })}
        className="rounded bg-accent/30 text-foreground"
      >
        {text.slice(index, index + needle.length)}
      </mark>
      {text.slice(index + needle.length)}
    </>
  );
}
