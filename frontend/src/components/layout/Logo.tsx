import Link from "next/link";
import { NexusMark } from "@/components/visual/NexusMark";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2.5">
      <NexusMark size={28} />
      <span className="text-base font-semibold tracking-tight text-foreground">NEXUS AI</span>
    </Link>
  );
}
