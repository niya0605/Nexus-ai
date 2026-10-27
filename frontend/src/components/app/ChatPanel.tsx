"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { SendIcon } from "@/components/icons";
import { AnswerTurn, type Turn } from "@/components/app/AnswerTurn";
import { askQuestionStream, getConversation, type ChatMessage, type Citation } from "@/lib/api";

interface ChatPanelProps {
  workspaceId: string;
  /** Scope new conversations to one document (continued ones keep their own scope). */
  documentId?: string;
  conversationId: string | null;
  onConversationChange: (id: string) => void;
  /** Called after every answered question, e.g. to refresh a conversation list. */
  onActivity?: () => void;
  selected: Citation | null;
  /** A source the user clicked. */
  onSelect: (c: Citation) => void;
  /** A source picked automatically (latest answer); defaults to onSelect. */
  onAutoSelect?: (c: Citation) => void;
  inputLabel: string;
  placeholder: string;
  disabled?: boolean;
  suggestions?: string[];
  empty?: ReactNode;
  showOpenLinks?: boolean;
  compact?: boolean;
}

function messagesToTurns(messages: ChatMessage[]): Turn[] {
  const turns: Turn[] = [];
  for (const m of messages) {
    if (m.role === "user") {
      turns.push({ question: m.content });
    } else if (turns.length) {
      // Answers saved before [n] markers existed list every source, numbered in order.
      const citations = m.citations.map((c, i) => ({ ...c, number: c.number ?? i + 1 }));
      turns[turns.length - 1] = { ...turns[turns.length - 1], answer: m.content, citations };
    }
  }
  return turns;
}

export function ChatPanel({
  workspaceId,
  documentId,
  conversationId,
  onConversationChange,
  onActivity,
  selected,
  onSelect,
  onAutoSelect,
  inputLabel,
  placeholder,
  disabled = false,
  suggestions = [],
  empty,
  showOpenLinks = true,
  compact = false,
}: ChatPanelProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  // The conversation this panel just created — already on screen, no reload needed.
  const createdHere = useRef<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLoadError(null);
    if (!conversationId) {
      createdHere.current = null;
      setTurns([]);
      return;
    }
    if (conversationId === createdHere.current) return;

    let cancelled = false;
    setLoadingHistory(true);
    getConversation(workspaceId, conversationId)
      .then((conversation) => {
        if (cancelled) return;
        const loaded = messagesToTurns(conversation.messages);
        setTurns(loaded);
        const lastCitation = loaded.at(-1)?.citations?.[0];
        if (lastCitation) (onAutoSelect ?? onSelect)(lastCitation);
      })
      .catch((err) => !cancelled && setLoadError(err instanceof Error ? err.message : "Could not load this conversation."))
      .finally(() => !cancelled && setLoadingHistory(false));
    return () => {
      cancelled = true;
    };
    // onSelect is a parent callback; reloading on its identity would refetch needlessly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, conversationId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns]);

  async function ask(question: string) {
    if (asking || disabled || !question.trim()) return;
    setAsking(true);
    setInput("");
    setTurns((prev) => [...prev, { question }]);
    const updateLast = (update: (turn: Turn) => Turn) =>
      setTurns((prev) => [...prev.slice(0, -1), update(prev[prev.length - 1])]);
    try {
      const result = await askQuestionStream(workspaceId, question, { documentId, conversationId }, (text) =>
        updateLast((turn) => ({ ...turn, answer: (turn.answer ?? "") + text, streaming: true })),
      );
      updateLast(() => ({ question, answer: result.message, citations: result.citations }));
      if (result.conversation_id !== conversationId) {
        createdHere.current = result.conversation_id;
        onConversationChange(result.conversation_id);
      }
      if (result.citations[0]) (onAutoSelect ?? onSelect)(result.citations[0]);
      onActivity?.();
    } catch (err) {
      // A partly streamed answer was not saved, so don't leave it on screen.
      updateLast(() => ({ question, error: err instanceof Error ? err.message : "Something went wrong." }));
    } finally {
      setAsking(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    ask(input.trim());
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className={compact ? "space-y-8 px-5 py-5" : "mx-auto w-full max-w-2xl space-y-10 px-6 py-8 lg:px-10"}>
          {loadingHistory && <p className="text-sm text-muted">Loading conversation…</p>}
          {loadError && <p className="text-sm text-red-400">{loadError}</p>}
          {!loadingHistory && !loadError && turns.length === 0 && empty}
          {turns.map((turn, i) => (
            <AnswerTurn key={i} turn={turn} selected={selected} onSelect={onSelect} showOpenLinks={showOpenLinks} />
          ))}
          <div ref={endRef} />
        </div>
      </div>

      <div className={`border-t border-border ${compact ? "px-5 py-3" : "px-6 py-4 lg:px-10"}`}>
        <div className={compact ? "" : "mx-auto w-full max-w-2xl"}>
          {turns.length === 0 && suggestions.length > 0 && !disabled && (
            <div className="mb-3 flex flex-wrap gap-2">
              {suggestions.map((q) => (
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
          <form
            onSubmit={onSubmit}
            className="flex items-center gap-2 rounded-xl border border-accent/15 bg-surface p-2 transition-colors duration-200 focus-within:border-accent/60"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={placeholder}
              aria-label={inputLabel}
              disabled={disabled}
              className="h-10 flex-1 bg-transparent px-3 text-sm text-foreground placeholder:text-muted focus:outline-none disabled:cursor-not-allowed"
            />
            <button
              type="submit"
              disabled={!input.trim() || asking || disabled}
              aria-label="Submit question"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground transition-colors duration-150 hover:bg-accent-hover disabled:opacity-40"
            >
              <SendIcon />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
