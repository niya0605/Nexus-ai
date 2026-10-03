import type { ReactNode } from "react";
import { Logo } from "@/components/layout/Logo";

interface AuthCardProps {
  heading: string;
  subheading: string;
  children: ReactNode;
  footer: ReactNode;
}

/** Shared chrome for /login and /register: centered card, logo, footer link. */
export function AuthCard({ heading, subheading, children, footer }: AuthCardProps) {
  return (
    <div className="bg-grid flex min-h-screen flex-col items-center justify-center px-6 py-12">
      <div className="mb-8">
        <Logo />
      </div>

      <div className="w-full max-w-sm rounded-2xl border border-border bg-surface p-8 shadow-2xl shadow-black/40">
        <div className="mb-6 text-center">
          <h1 className="text-xl font-semibold text-foreground">{heading}</h1>
          <p className="mt-1 text-sm text-muted">{subheading}</p>
        </div>
        {children}
      </div>

      <p className="mt-6 text-sm text-muted">{footer}</p>
    </div>
  );
}
