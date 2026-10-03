"use client";

import { useCallback, useEffect, useState } from "react";
import { getWorkspaceId, listDocuments, type DocumentItem } from "@/lib/api";

/** Resolves the user's workspace and keeps its document list loaded. */
export function useWorkspaceDocuments() {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (id: string) => {
    setDocuments(await listDocuments(id));
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const id = await getWorkspaceId();
        if (cancelled) return;
        setWorkspaceId(id);
        const docs = await listDocuments(id);
        if (!cancelled) setDocuments(docs);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load your workspace.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    workspaceId,
    documents,
    loading,
    error,
    refreshDocuments: () => (workspaceId ? refresh(workspaceId) : Promise.resolve()),
  };
}
