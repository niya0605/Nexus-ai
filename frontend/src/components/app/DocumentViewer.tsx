"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { SendIcon, SparkleIcon } from "@/components/icons";
import { AnswerTurn, type Turn } from "@/components/app/AnswerTurn";
import { CenteredMessage } from "@/components/app/AskView";
import {
  askQuestion,
  documentFileUrl,
  getDocument,
  getDocumentText,
  getWorkspaceId,
  type Citation,
  type DocumentItem,
} from "@/lib/api";

type Tab = "original" | "text";

export function DocumentViewer({ documentId }: { documentId: string }) {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [doc, setDoc] = useState<DocumentItem | null>(null);
  const [text, setText] = useState("");
  const [hasOriginal, setHasOriginal] = useState(false);
  const [tab, setTab] = useState<Tab>("text");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [asking, setAsking] = useState(false);
  const [selected, setSelected] = useState<Citation | null>(null);

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

  async function ask(question: string) {
    if (!workspaceId || asking || !question.trim()) return;
    setAsking(true);
    setInput("");
    setTurns((prev) => [{ question }, ...prev]);
    try {
      const result = await askQuestion(workspaceId, question, documentId);
      setTurns((prev) => [{ question, answer: result.message, citations: result.citations }, ...prev.slice(1)]);
      setSelected(result.citations[0] ?? null);
    } catch (err) {
      setTurns((prev) => [
        { question, error: err instanceof Error ? err.message : "Something went wrong." },
        ...prev.slice(1),
      ]);
    } finally {
      setAsking(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    ask(input.trim());
  }

  if (loadError) return <CenteredMessage text={loadError} error />;
  if (!doc || !workspaceId) return <CenteredMessage text="Loading document…" />;

  const canShowOriginal = hasOriginal && doc.file_type !== "docx";

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
            title={doc.title}
            src={documentFileUrl(workspaceId, documentId)}
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
          <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <SparkleIcon width={14} height={14} className="text-accent" />
            Ask about this document
          </h2>
          <form
            onSubmit={onSubmit}
            className="mt-3 flex items-center gap-2 rounded-xl border border-accent/15 bg-background p-1.5 focus-within:border-accent/60"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={doc.status === "ready" ? "Ask a question…" : "This document has no readable text"}
              disabled={doc.status !== "ready"}
              aria-label="Ask about this document"
              className="h-9 flex-1 bg-transparent px-2 text-sm text-foreground placeholder:text-muted focus:outline-none disabled:cursor-not-allowed"
            />
            <button
              type="submit"
              disabled={!input.trim() || asking || doc.status !== "ready"}
              aria-label="Submit question"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground hover:bg-accent-hover disabled:opacity-40"
            >
              <SendIcon />
            </button>
          </form>
          {doc.status === "ready" && turns.length === 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {["Summarize this document", "What are the key points?"].map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => ask(q)}
                  className="rounded-full border border-border px-3 py-1 text-xs text-muted hover:border-accent/50 hover:text-foreground"
                >
                  {q}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex-1 space-y-8 overflow-y-auto px-5 py-5">
          {turns.length === 0 ? (
            <p className="text-sm text-muted">Answers use only this document. Click a source to highlight it in the text.</p>
          ) : (
            turns.map((turn, i) => (
              <AnswerTurn
                key={turns.length - i}
                turn={turn}
                selected={selected}
                showOpenLinks={false}
                onSelect={(c) => {
                  setSelected(c);
                  setTab("text");
                }}
              />
            ))
          )}
        </div>
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
