"use client";

import Link from "next/link";
import { Logo } from "@/components/layout/Logo";
import { buttonVariants } from "@/components/ui/Button";
import { ChevronDownIcon } from "@/components/icons";

const NAV_LINKS = [
  { label: "Product", href: "#product-preview", hasMenu: true },
  { label: "Security", href: undefined, hasMenu: false },
  { label: "Docs", href: undefined, hasMenu: false },
  { label: "Pricing", href: undefined, hasMenu: false },
  { label: "Company", href: undefined, hasMenu: true },
] as const;

export function Navbar() {
  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-background/90 backdrop-blur-sm">
      <div className="flex h-[82px] w-full items-center justify-between gap-6 px-[clamp(1.75rem,6vw,6.875rem)]">
        <Logo />

        <nav aria-label="Primary" className="hidden flex-1 items-center justify-center gap-[34px] md:flex">
          {NAV_LINKS.map((link) =>
            link.href ? (
              <a
                key={link.label}
                href={link.href}
                className="flex items-center gap-1 text-sm text-muted transition-colors duration-150 hover:text-foreground"
              >
                {link.label}
                {link.hasMenu && <ChevronDownIcon width={14} height={14} />}
              </a>
            ) : (
              // Not wired up yet — rendered identically for IA
              // completeness, but inert rather than a dead "#" link.
              <button
                key={link.label}
                type="button"
                disabled
                className="flex cursor-default items-center gap-1 text-sm text-muted/50"
              >
                {link.label}
                {link.hasMenu && <ChevronDownIcon width={14} height={14} />}
              </button>
            ),
          )}
        </nav>

        <div className="flex items-center gap-2 sm:gap-3">
          <Link href="/login" className={buttonVariants({ variant: "secondary", size: "md" })}>
            Log in
          </Link>
          <Link href="/register" className={buttonVariants({ variant: "primary", size: "md", className: "px-5" })}>
            Get started
          </Link>
        </div>
      </div>
    </header>
  );
}
