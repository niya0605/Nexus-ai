"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { SendIcon, SparkleIcon } from "@/components/icons";
import { AnswerTurn, type Turn } from "@/components/app/AnswerTurn";
import { DocumentUploader } from "@/components/app/DocumentUploader";
import { DocumentList } from "@/components/app/DocumentList";
import { askQuestion, type Citation } from "@/lib/api";
import { useWorkspaceDocuments } from "@/lib/useWorkspace";

const SUGGESTIONS = ["Summarize my documents", "What are the key points?", "List any dates or deadlines mentioned"];

export function AskView() {
  const { workspaceId, documents, loading, error, refreshDocuments } = useWorkspaceDocuments();
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [asking, setAsking] = useState(false);
  const [selected, setSelected] = useState<Citation | null>(null);

  const readyCount = documents.filter((d) => d.status === "ready").length;

  async function ask(question: string) {
    if (!workspaceId || asking || !question.trim()) return;
    setAsking(true);
    setInput("");
    setTurns((prev) => [{ question }, ...prev]);
    try {
      const result = await askQuestion(workspaceId, question);
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

  if (loading) return <CenteredMessage text="Loading your workspace…" />;
  if (error || !workspaceId) return <CenteredMessage text={error ?? "Could not load your workspace."} error />;

  return (
    <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_340px]">
      <main className="flex flex-col overflow-y-auto">
        <div className="border-b border-border px-6 py-4 lg:px-10">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <SparkleIcon width={14} height={14} className="text-accent" />
            Ask Nexus
          </h2>
          <form
            onSubmit={onSubmit}
            className="mt-4 flex items-center gap-2 rounded-xl border border-accent/15 bg-surface p-2 transition-colors duration-200 focus-within:border-accent/60"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={readyCount ? "Ask anything about your documents…" : "Upload a document first →"}
              aria-label="Ask Nexus"
              disabled={!readyCount}
              className="h-10 flex-1 bg-transparent px-3 text-sm text-foreground placeholder:text-muted focus:outline-none disabled:cursor-not-allowed"
            />
            <button
              type="submit"
              disabled={!input.trim() || asking || !readyCount}
              aria-label="Submit question"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground transition-colors duration-150 hover:bg-accent-hover disabled:opacity-40"
            >
              <SendIcon />
            </button>
          </form>
          {readyCount > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {SUGGESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  disabled={asking}
                  onClick={() => ask(q)}
                  className="rounded-full border border-border px-3 py-1 text-xs text-muted transition-colors duration-150 hover:border-accent/50 hover:text-foreground disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mx-auto w-full max-w-2xl flex-1 space-y-10 px-6 py-8 lg:px-10">
          {turns.length === 0 && (
            <div className="rounded-xl border border-border bg-surface px-6 py-10 text-center">
              {readyCount ? (
                <p className="text-sm text-muted">
                  {readyCount} document{readyCount === 1 ? "" : "s"} ready. Ask a question above — answers come
                  from your documents, with sources.
                </p>
              ) : (
                <>
                  <p className="text-sm text-foreground">You haven&apos;t uploaded any documents yet.</p>
                  <p className="mt-1 text-sm text-muted">Upload one on the right (or on the Documents page) to start asking.</p>
                </>
              )}
            </div>
          )}

          {turns.map((turn, i) => (
            <AnswerTurn key={turns.length - i} turn={turn} selected={selected} onSelect={setSelected} />
          ))}
        </div>
      </main>

      <aside className="hidden flex-col divide-y divide-border overflow-y-auto border-l border-border bg-surface lg:flex">
        <section className="px-5 py-4">
          <h2 className="text-sm font-semibold text-foreground">Source preview</h2>
          {selected ? (
            <div className="mt-3">
              <p className="truncate text-sm font-medium text-foreground">{selected.document_title}</p>
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
