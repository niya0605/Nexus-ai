import { UploadIcon, AskIcon } from "@/components/icons";

const ACTIVITY = [
  { actor: "Priya", action: "uploaded", target: "Q3 Roadmap v2.1", time: "2m ago", Icon: UploadIcon },
  { actor: "Marcus", action: "asked", target: "“What's our Q3 revenue target?”", time: "18m ago", Icon: AskIcon },
  { actor: "Dana", action: "uploaded", target: "Leadership Meeting Notes", time: "1h ago", Icon: UploadIcon },
];

/** Static illustrative activity feed. */
export function TeamActivity() {
  return (
    <div>
      <div className="flex items-center justify-between border-b border-border px-5 py-4">
        <h2 className="text-sm font-semibold text-foreground">Team activity</h2>
        <button type="button" disabled className="cursor-default text-xs text-muted/50">
          View all
        </button>
      </div>
      <ul className="space-y-3 px-5 py-4">
        {ACTIVITY.map((item, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm">
            <span
              aria-hidden="true"
              className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-raised text-accent"
            >
              <item.Icon width={12} height={12} />
            </span>
            <p className="text-muted">
              <span className="text-foreground">{item.actor}</span> {item.action}{" "}
              <span className="text-foreground">{item.target}</span>
              <span className="block text-xs text-muted/70">{item.time}</span>
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
