const CONVERSATIONS = ["Q3 roadmap changes", "Budget for AI tools", "Onboarding process", "Security policy update"];

/** Static illustrative list — no thread-switching wired up yet (see DashboardShell). */
export function RecentConversations() {
  return (
    <div>
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="text-sm font-semibold text-foreground">Recent conversations</h2>
        <button type="button" disabled className="cursor-default text-xs text-muted/50">
          View all
        </button>
      </div>
      <ul className="px-2 py-2">
        {CONVERSATIONS.map((title) => (
          <li key={title}>
            <button
              type="button"
              className="w-full truncate rounded-lg px-3 py-2 text-left text-sm text-muted transition-colors duration-150 hover:bg-surface-raised hover:text-foreground"
            >
              {title}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
