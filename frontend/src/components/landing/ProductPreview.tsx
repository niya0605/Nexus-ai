"use client";

import { useState } from "react";
import { Container } from "@/components/layout/Container";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { DashboardTopBar } from "@/components/dashboard/DashboardTopBar";
import { AskPanel } from "@/components/dashboard/AskPanel";
import { AnswerPanel } from "@/components/dashboard/AnswerPanel";
import { SourcePreview } from "@/components/dashboard/SourcePreview";
import { RecentConversations } from "@/components/dashboard/RecentConversations";
import { TeamActivity } from "@/components/dashboard/TeamActivity";
import { MOCK_ANSWERS, type AnswerData } from "@/lib/mockKnowledge";

const THINKING_DELAY_MS = 500;

/**
 * A large, framed, genuinely interactive preview of the real product —
 * built from the exact same components as /dashboard (Sidebar, AskPanel,
 * AnswerPanel, SourcePreview, RecentConversations, TeamActivity), just
 * contained to a fixed height instead of the full viewport. This is
 * deliberately not a screenshot: clicking a suggested question or a
 * source here does the same thing it does on /dashboard.
 */
export function ProductPreview() {
  const [answer, setAnswer] = useState<AnswerData>(MOCK_ANSWERS[0]);
  const [isThinking, setIsThinking] = useState(false);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(MOCK_ANSWERS[0].sources[0]?.id ?? null);

  function handleAsk(question: string) {
    const normalized = question.trim().toLowerCase();
    const match =
      MOCK_ANSWERS.find((candidate) => candidate.question.toLowerCase() === normalized) ??
      MOCK_ANSWERS[Math.floor(Math.random() * MOCK_ANSWERS.length)];

    setIsThinking(true);
    window.setTimeout(() => {
      setAnswer(match);
      setSelectedSourceId(match.sources[0]?.id ?? null);
      setIsThinking(false);
    }, THINKING_DELAY_MS);
  }

  const selectedSource = answer.sources.find((source) => source.id === selectedSourceId) ?? null;

  return (
    <section id="product-preview" className="pb-24 sm:pb-32">
      <Container>
        <div className="mx-auto mb-8 max-w-2xl text-center">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            The actual product, not a screenshot.
          </h2>
          <p className="mt-2 text-muted">
            Every answer traces back to the exact document and page it came from. Try it below.
          </p>
        </div>

        <div className="mx-auto grid h-[640px] max-w-6xl grid-cols-1 overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl shadow-black/40 md:grid-cols-[220px_minmax(0,1fr)] lg:grid-cols-[240px_minmax(0,1fr)]">
          <Sidebar className="hidden md:flex" />

          <div className="flex h-full min-w-0 flex-col overflow-hidden">
            <DashboardTopBar />

            <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_300px]">
              <div className="flex flex-col overflow-y-auto">
                <div className="border-b border-border px-6 py-4">
                  <AskPanel onAsk={handleAsk} />
                </div>
                <div className="flex-1 px-6 py-6">
                  <AnswerPanel
                    answer={answer}
                    isThinking={isThinking}
                    selectedSourceId={selectedSourceId}
                    onSelectSource={setSelectedSourceId}
                  />
                </div>
              </div>

              <aside className="hidden flex-col divide-y divide-border overflow-y-auto border-l border-border bg-surface lg:flex">
                <SourcePreview source={selectedSource} />
                <RecentConversations />
                <TeamActivity />
              </aside>
            </div>
          </div>
        </div>
      </Container>
    </section>
  );
}
