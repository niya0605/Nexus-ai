import type { Metadata } from "next";
import { AppShell } from "@/components/app/AppShell";
import { DocumentsView } from "@/components/app/DocumentsView";

export const metadata: Metadata = {
  title: "Documents — Nexus AI",
};

export default function DocumentsPage() {
  return (
    <AppShell>
      <DocumentsView />
    </AppShell>
  );
}
