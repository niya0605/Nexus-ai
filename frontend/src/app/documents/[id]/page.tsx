import type { Metadata } from "next";
import { AppShell } from "@/components/app/AppShell";
import { DocumentViewer } from "@/components/app/DocumentViewer";

export const metadata: Metadata = {
  title: "Document — Nexus AI",
};

export default async function DocumentPage(props: PageProps<"/documents/[id]">) {
  const { id } = await props.params;
  const { page } = await props.searchParams;
  const initialPage = Number(Array.isArray(page) ? page[0] : page);
  return (
    <AppShell>
      <DocumentViewer documentId={id} initialPage={initialPage > 0 ? Math.floor(initialPage) : undefined} />
    </AppShell>
  );
}
