import Link from "next/link";
import { Container } from "@/components/layout/Container";
import { buttonVariants } from "@/components/ui/Button";
import { KnowledgeWorld } from "@/components/visual/KnowledgeWorld";
import { CapabilityItem } from "@/components/landing/CapabilityItem";
import { UploadIcon, AskIcon, LevelUpIcon, PlayIcon } from "@/components/icons";

export function Hero() {
  return (
    <section className="relative overflow-hidden pb-16 sm:pb-24">
      <Container>
        <div className="grid items-center gap-5 pt-12 sm:pt-16 lg:grid-cols-[400px_minmax(0,1fr)] lg:gap-6 lg:pt-20">
          {/* Text column */}
          <div className="text-center lg:text-left">
            <p className="mb-6 inline-flex items-center rounded-full border border-accent/15 bg-surface px-3.5 py-1.5 font-mono text-[11px] tracking-[0.08em] text-accent/80 uppercase">
              AI Knowledge Assistant
            </p>
            <h1 className="text-[clamp(2.75rem,5vw,4rem)] leading-[0.98] font-semibold tracking-[-0.03em] text-foreground">
              Your team&apos;s
              <br />
              knowledge.
              <br />
              <span className="text-accent">Levelled up.</span>
            </h1>
            <p className="mx-auto mt-6 max-w-[325px] text-[15px] leading-[1.65] text-pretty text-muted lg:mx-0">
              Nexus AI helps teams search, understand and act on company
              knowledge. All in one secure workspace.
            </p>
            <div className="mt-7 flex flex-col justify-center gap-2.5 sm:flex-row lg:justify-start">
              <Link href="/register" className={buttonVariants({ variant: "primary", className: "h-[50px] px-5 whitespace-nowrap" })}>
                Get started for free →
              </Link>
              <Link href="#product-preview" className={buttonVariants({ variant: "secondary", className: "h-[50px] gap-2 px-5 whitespace-nowrap" })}>
                <PlayIcon width={14} height={14} />
                See how it works
              </Link>
            </div>

            <div className="mx-auto mt-10 grid max-w-md grid-cols-1 gap-3 text-left sm:grid-cols-3 lg:mx-0">
              <CapabilityItem
                icon={<UploadIcon width={16} height={16} />}
                label="Upload"
                description={"Bring your docs\ninto the game"}
              />
              <CapabilityItem icon={<AskIcon width={16} height={16} />} label="Ask" description={"Get answers\nwith sources"} />
              <CapabilityItem
                icon={<LevelUpIcon width={16} height={16} />}
                label="Level up"
                description={"Your team gets\nsmarter, together"}
              />
            </div>
          </div>

          <div>
            <KnowledgeWorld />
          </div>
        </div>
      </Container>
    </section>
  );
}
