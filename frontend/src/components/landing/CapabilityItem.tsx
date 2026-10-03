import type { ReactNode } from "react";

interface CapabilityItemProps {
  icon: ReactNode;
  label: string;
  description: string;
}

/** One compact "Upload / Ask / Level up" capability row item under the hero CTAs. */
export function CapabilityItem({ icon, label, description }: CapabilityItemProps) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="mt-0.5 flex h-[31px] w-[31px] shrink-0 items-center justify-center rounded-lg border border-white/10 text-accent">
        {icon}
      </span>
      <div>
        <p className="font-mono text-[11px] font-medium tracking-wide text-foreground uppercase">{label}</p>
        <p className="mt-1.5 text-[11px] leading-snug whitespace-pre-line text-muted">{description}</p>
      </div>
    </div>
  );
}
