/**
 * The small pixel/game-inspired brand mark used next to the "NEXUS AI"
 * wordmark — a compact robot/helmet face, matching the reference
 * header's icon. Deliberately simple (a handful of shapes), consistent
 * with the same restrained pixel-art language used everywhere else.
 */
export function NexusMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <circle cx="9" cy="3.2" r="1.3" fill="var(--accent)" />
      <circle cx="19" cy="3.2" r="1.3" fill="var(--accent)" />
      <line x1="9" y1="4.3" x2="9" y2="7" stroke="var(--accent)" strokeWidth="1.2" />
      <line x1="19" y1="4.3" x2="19" y2="7" stroke="var(--accent)" strokeWidth="1.2" />
      <rect x="3.5" y="7" width="21" height="17" rx="5" stroke="var(--foreground)" strokeWidth="1.6" fill="var(--surface-raised)" />
      <circle cx="11" cy="15.5" r="2" fill="var(--accent)" />
      <circle cx="17" cy="15.5" r="2" fill="var(--accent)" />
    </svg>
  );
}
