"use client";

import { useState, type FormEvent } from "react";
import { SendIcon, SparkleIcon } from "@/components/icons";
import { SUGGESTED_QUESTIONS } from "@/lib/mockKnowledge";

interface AskPanelProps {
  onAsk: (question: string) => void;
}

/** The Ask Nexus question input, with suggestions. Global search lives in DashboardTopBar. */
export function AskPanel({ onAsk }: AskPanelProps) {
  const [input, setInput] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed) return;
    onAsk(trimmed);
    setInput("");
  }

  return (
    <div>
      <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <SparkleIcon width={14} height={14} className="text-accent" />
        Ask Nexus
      </h2>

      <form
        onSubmit={handleSubmit}
        className="mt-4 flex items-center gap-2 rounded-xl border border-accent/15 bg-surface p-2 transition-colors duration-200 focus-within:border-accent/60"
      >
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          type="text"
          placeholder="What changed in the Q3 roadmap?"
          aria-label="Ask Nexus"
          className="h-10 flex-1 bg-transparent px-3 text-sm text-foreground placeholder:text-muted focus:outline-none"
        />
        <button
          type="submit"
          disabled={!input.trim()}
          aria-label="Submit question"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground transition-colors duration-150 hover:bg-accent-hover disabled:opacity-40"
        >
          <SendIcon />
        </button>
      </form>

      <div className="mt-3 flex flex-wrap gap-2">
        {SUGGESTED_QUESTIONS.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onAsk(question)}
            className="rounded-full border border-border px-3 py-1 text-xs text-muted transition-colors duration-150 hover:border-accent/50 hover:text-foreground"
          >
            {question}
          </button>
        ))}
      </div>
    </div>
  );
}
