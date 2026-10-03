import type { ReactNode } from "react";

export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={["mx-auto w-full max-w-6xl px-6", className].filter(Boolean).join(" ")}>{children}</div>;
}
