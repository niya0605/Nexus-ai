"use client";

import { useState } from "react";
import { SearchIcon, BellIcon, SlidersIcon, ChevronDownIcon } from "@/components/icons";
import { logout } from "@/lib/api";

/** The dashboard's top utility strip — search on the left, account menu on the right. */
export function DashboardTopBar({ userInitial = "M" }: { userInitial?: string }) {
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <div className="flex items-center gap-3 border-b border-border bg-surface px-4 py-3 lg:px-6">
      <div className="relative max-w-xl flex-1">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" width={16} height={16} />
        <input
          type="search"
          placeholder="Search documents, collections, or ask anything..."
          className="h-9 w-full rounded-lg border border-border bg-background pr-14 pl-9 text-sm text-foreground placeholder:text-muted transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
        <span className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted">
          ⌘K
        </span>
      </div>

      <button
        type="button"
        aria-label="Notifications"
        className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border text-muted transition-colors duration-150 hover:border-zinc-600 hover:text-foreground sm:flex"
      >
        <BellIcon width={16} height={16} />
      </button>
      <button
        type="button"
        aria-label="Preferences"
        disabled
        className="hidden h-9 w-9 shrink-0 cursor-default items-center justify-center rounded-lg border border-border text-muted/50 sm:flex"
      >
        <SlidersIcon width={16} height={16} />
      </button>

      <div className="relative">
        <button
          type="button"
          onClick={() => setMenuOpen(!menuOpen)}
          className="flex shrink-0 items-center gap-1 rounded-lg border border-border py-1 pr-1.5 pl-1 transition-colors duration-150 hover:border-zinc-600"
        >
          <span
            aria-hidden="true"
            className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-accent to-accent-hover text-xs font-semibold text-accent-foreground"
          >
            {userInitial}
          </span>
          <ChevronDownIcon width={14} height={14} className="text-muted" />
        </button>

        {menuOpen && (
          <div className="absolute right-0 top-full z-50 mt-1 w-36 rounded-lg border border-border bg-surface p-1 shadow-lg">
            <button
              type="button"
              onClick={logout}
              className="block w-full rounded-md px-3 py-2 text-left text-sm text-foreground transition hover:bg-accent/10"
            >
              Logout
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
