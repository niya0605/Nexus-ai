export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export interface DocumentItem {
  id: string;
  title: string;
  file_type: string;
  file_size_bytes: number;
  status: "uploading" | "processing" | "ready" | "failed" | "archived" | "deleted";
  created_at: string;
}

export interface Citation {
  chunk_id: string;
  document_id: string;
  document_title: string;
  excerpt: string;
}

export interface ChatAnswer {
  message: string;
  citations: Citation[];
}

async function rawFetch(path: string, init?: RequestInit) {
  return fetch(`${API_BASE}${path}`, { ...init, credentials: "include" });
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body?.error?.message ?? body?.detail ?? `Request failed (${res.status})`;
  } catch {
    return `Request failed (${res.status})`;
  }
}

/** Fetch with cookie auth; on 401 tries one token refresh, then sends the user to /login. */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res = await rawFetch(path, init);

  if (res.status === 401) {
    const refreshed = await rawFetch("/auth/refresh", { method: "POST" });
    if (refreshed.ok) {
      res = await rawFetch(path, init);
    }
  }

  if (res.status === 401) {
    window.location.href = "/login";
    throw new ApiError("Please log in again.", 401);
  }

  if (!res.ok) {
    throw new ApiError(await errorMessage(res), res.status);
  }

  if (res.status === 204) return undefined as T;
  const body = await res.json();
  return body.data as T;
}

let workspaceIdPromise: Promise<string> | null = null;

/** The user's first workspace, creating one on first use. Concurrent callers share one request. */
export function getWorkspaceId(): Promise<string> {
  workspaceIdPromise ??= resolveWorkspaceId().catch((err) => {
    workspaceIdPromise = null;
    throw err;
  });
  return workspaceIdPromise;
}

async function resolveWorkspaceId(): Promise<string> {
  const workspaces = await apiFetch<{ id: string }[]>("/workspaces");
  if (workspaces.length > 0) return workspaces[0].id;

  const created = await apiFetch<{ workspace: { id: string } }>("/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "My Knowledge Base" }),
  });
  return created.workspace.id;
}

export function listDocuments(workspaceId: string) {
  return apiFetch<DocumentItem[]>(`/documents/${workspaceId}`);
}

export function uploadDocument(workspaceId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<DocumentItem>(`/documents/${workspaceId}/upload`, { method: "POST", body: form });
}

export function getDocument(workspaceId: string, documentId: string) {
  return apiFetch<DocumentItem>(`/documents/${workspaceId}/${documentId}`);
}

export function getDocumentText(workspaceId: string, documentId: string) {
  return apiFetch<{ text: string; has_original: boolean }>(`/documents/${workspaceId}/${documentId}/text`);
}

export function documentFileUrl(workspaceId: string, documentId: string) {
  return `${API_BASE}/documents/${workspaceId}/${documentId}/file`;
}

export function askQuestion(workspaceId: string, message: string, documentId?: string) {
  return apiFetch<ChatAnswer>(`/chat/${workspaceId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, document_id: documentId ?? null }),
  });
}

export async function logout() {
  workspaceIdPromise = null;
  try {
    await apiFetch<void>("/auth/logout", { method: "POST" });
  } catch {
    // Already logged out or session expired — either way, go to login.
  } finally {
    window.location.href = "/login";
  }
}
