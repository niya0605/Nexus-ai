"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/layout/Logo";
import {
  AskIcon,
  DocumentsIcon,
  CollectionsIcon,
  SummariesIcon,
  InsightsIcon,
  ActivityIcon,
  MembersIcon,
  IntegrationsIcon,
  SettingsIcon,
} from "@/components/icons";

const LIVE_ITEMS = [
  { label: "Ask Nexus", Icon: AskIcon, href: "/dashboard" },
  { label: "Documents", Icon: DocumentsIcon, href: "/documents" },
] as const;

const SOON_ITEMS = [
  { label: "Collections", Icon: CollectionsIcon },
  { label: "Summaries", Icon: SummariesIcon },
  { label: "Insights", Icon: InsightsIcon },
  { label: "Activity", Icon: ActivityIcon },
  { label: "Members", Icon: MembersIcon },
  { label: "Integrations", Icon: IntegrationsIcon },
  { label: "Settings", Icon: SettingsIcon },
] as const;

/** The dashboard's left rail — also embedded in the landing page's product preview. */
export function Sidebar({ className = "" }: { className?: string }) {
  const pathname = usePathname();
  const activeHref = pathname.startsWith("/documents") ? "/documents" : "/dashboard";

  return (
    <aside className={`${className} flex-col border-r border-border bg-surface`.trim()}>
      <div className="border-b border-border px-5 py-4">
        <Logo />
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4" aria-label="Dashboard">
        {LIVE_ITEMS.map(({ label, Icon, href }) => {
          const active = href === activeHref;
          return (
            <Link
              key={label}
              href={href}
              aria-current={active ? "page" : undefined}
              className={[
                "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-150",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                active ? "bg-accent-soft text-foreground" : "text-muted hover:bg-surface-raised hover:text-foreground",
              ].join(" ")}
            >
              <Icon className={active ? "text-accent" : "text-muted"} />
              {label}
            </Link>
          );
        })}
        {SOON_ITEMS.map(({ label, Icon }) => (
          <button
            key={label}
            type="button"
            disabled
            className="flex w-full cursor-default items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted/60"
          >
            <Icon className="text-muted/60" />
            {label}
            <span className="ml-auto font-pixel text-[9px] tracking-wide text-muted/50">SOON</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}
