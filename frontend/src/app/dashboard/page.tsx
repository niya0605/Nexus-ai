import type { Metadata } from "next";
import { AppShell } from "@/components/app/AppShell";
import { AskView } from "@/components/app/AskView";

export const metadata: Metadata = {
  title: "Ask Nexus — Nexus AI",
  description: "Ask your team's knowledge base anything, with every answer cited.",
};

export default async function DashboardPage(props: PageProps<"/dashboard">) {
  const { c } = await props.searchParams;
  const conversationId = Array.isArray(c) ? c[0] : c;
  return (
    <AppShell>
      <AskView initialConversationId={conversationId} />
    </AppShell>
  );
}
