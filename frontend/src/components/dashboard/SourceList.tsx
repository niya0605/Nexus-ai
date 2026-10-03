import { SourceCard } from "@/components/dashboard/SourceCard";
import type { Source } from "@/lib/mockKnowledge";

interface SourceListProps {
  sources: Source[];
  selectedSourceId: string | null;
  onSelectSource: (id: string) => void;
}

export function SourceList({ sources, selectedSourceId, onSelectSource }: SourceListProps) {
  return (
    <div className="space-y-2">
      {sources.map((source) => (
        <SourceCard
          key={source.id}
          title={source.title}
          page={source.page}
          updatedLabel={source.updatedLabel}
          selected={source.id === selectedSourceId}
          onSelect={() => onSelectSource(source.id)}
        />
      ))}
    </div>
  );
}
