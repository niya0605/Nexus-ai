"use client";

import { useRef, useState, type DragEvent } from "react";
import { uploadDocument } from "@/lib/api";

const ACCEPT = ".pdf,.docx,.txt,.md";

interface DocumentUploaderProps {
  workspaceId: string;
  onUploaded: () => void;
  compact?: boolean;
}

export function DocumentUploader({ workspaceId, onUploaded, compact = false }: DocumentUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setMessage(null);
    for (const file of Array.from(files)) {
      setUploading(file.name);
      try {
        const doc = await uploadDocument(workspaceId, file);
        setMessage(
          doc.status === "ready"
            ? { ok: true, text: `"${doc.title}" uploaded and ready to ask about.` }
            : { ok: false, text: `"${doc.title}" uploaded, but no readable text was found in it.` },
        );
        onUploaded();
      } catch (err) {
        setMessage({ ok: false, text: `${file.name}: ${err instanceof Error ? err.message : "upload failed"}` });
      }
    }
    setUploading(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    handleFiles(event.dataTransfer.files);
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={[
          "cursor-pointer rounded-xl border-2 border-dashed text-center transition-colors duration-150",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          compact ? "px-4 py-5" : "px-6 py-12",
          dragging ? "border-accent bg-accent-soft" : "border-border hover:border-accent/60",
        ].join(" ")}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <p className="text-sm font-medium text-foreground">
          {uploading ? `Uploading ${uploading}…` : "Click to choose files, or drag them here"}
        </p>
        <p className="mt-1 text-xs text-muted">PDF, DOCX, TXT or Markdown · up to 100 MB</p>
      </div>

      {message && (
        <p
          role="status"
          className={`mt-3 rounded-lg border px-3 py-2 text-sm ${
            message.ok
              ? "border-green-500/30 bg-green-500/10 text-green-400"
              : "border-red-500/30 bg-red-500/10 text-red-400"
          }`}
        >
          {message.text}
        </p>
      )}
    </div>
  );
}
