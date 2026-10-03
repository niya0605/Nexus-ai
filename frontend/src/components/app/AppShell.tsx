"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { DashboardTopBar } from "@/components/dashboard/DashboardTopBar";
import { Logo } from "@/components/layout/Logo";
import { logout } from "@/lib/api";

/** Logged-in layout: sidebar, top bar, and the page content. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid h-screen grid-cols-1 lg:grid-cols-[260px_minmax(0,1fr)]">
      <Sidebar className="hidden lg:flex" />
      <div className="flex h-full min-w-0 flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-border bg-surface px-4 py-3 lg:hidden">
          <Logo />
          <MobileNav />
        </div>
        <div className="hidden lg:block">
          <DashboardTopBar />
        </div>
        {children}
      </div>
    </div>
  );
}

function MobileNav() {
  return (
    <nav className="flex items-center gap-3 text-sm">
      <Link href="/dashboard" className="text-muted hover:text-foreground">
        Ask
      </Link>
      <Link href="/documents" className="text-muted hover:text-foreground">
        Documents
      </Link>
      <button type="button" onClick={logout} className="text-muted hover:text-foreground">
        Logout
      </button>
    </nav>
  );
}
