import type { Metadata } from "next";
import { AppShell } from "@/components/app/AppShell";
import { DocumentViewer } from "@/components/app/DocumentViewer";

export const metadata: Metadata = {
  title: "Document — Nexus AI",
};

export default async function DocumentPage(props: PageProps<"/documents/[id]">) {
  const { id } = await props.params;
  return (
    <AppShell>
      <DocumentViewer documentId={id} />
    </AppShell>
  );
}
