"use client";

import { DocumentUploader } from "@/components/app/DocumentUploader";
import { DocumentList } from "@/components/app/DocumentList";
import { useWorkspaceDocuments } from "@/lib/useWorkspace";

export function DocumentsView() {
  const { workspaceId, documents, loading, error, refreshDocuments } = useWorkspaceDocuments();

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-6 py-10">
        <h1 className="text-2xl font-semibold text-foreground">Documents</h1>
        <p className="mt-1 text-sm text-muted">
          Upload files here, then ask questions about them on the Ask Nexus page.
        </p>

        {loading && <p className="mt-8 text-sm text-muted">Loading your workspace…</p>}
        {error && <p className="mt-8 text-sm text-red-400">{error}</p>}

        {workspaceId && (
          <>
            <div className="mt-8">
              <DocumentUploader workspaceId={workspaceId} onUploaded={refreshDocuments} />
            </div>
            <h2 className="mt-10 mb-3 text-sm font-semibold text-foreground">
              Your documents ({documents.length})
            </h2>
            <DocumentList documents={documents} />
          </>
        )}
      </div>
    </main>
  );
}
