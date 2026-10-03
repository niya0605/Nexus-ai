import type { CSSProperties } from "react";
import { DocumentsIcon, ImageIcon, SpreadsheetIcon, ChartIcon, PresentationIcon, TextDocIcon } from "@/components/icons";

export type DocumentNodeType = "pdf" | "spreadsheet" | "image" | "chart" | "presentation" | "text";

const ICONS: Record<DocumentNodeType, typeof DocumentsIcon> = {
  pdf: DocumentsIcon,
  spreadsheet: SpreadsheetIcon,
  image: ImageIcon,
  chart: ChartIcon,
  presentation: PresentationIcon,
  text: TextDocIcon,
};

interface DocumentNodeProps {
  type: DocumentNodeType;
  style?: CSSProperties;
  delay?: number;
  /** A slight resting tilt (degrees) — a few cards angled, like paper index cards. */
  tilt?: number;
}

/**
 * One floating "knowledge object" card in the hero's KnowledgeWorld
 * scene — a warm paper card (matching the SourcePreview "paper" swatch
 * elsewhere in the product), not another dark chip. Against the scene's
 * navy background, a light card is what actually reads as a floating
 * document at a glance; a dark-on-dark chip nearly disappears.
 *
 * Two layers: the outer div holds position + a static tilt, the inner
 * div owns the float animation — a CSS animation on `transform`
 * replaces the whole property per-frame, so a static rotate() on the
 * same element would be clobbered the instant the animation starts.
 */
export function DocumentNode({ type, style, delay = 0, tilt = 0 }: DocumentNodeProps) {
  const Icon = ICONS[type];
  return (
    <div aria-hidden="true" className="absolute" style={{ transform: `rotate(${tilt}deg)`, ...style }}>
      {/* FIX #2: Increased card size and improved visibility
                 Card size:
                 - Was: h-10 w-10 (40px) — too small
                 - Now: h-12 w-12 (48px) — matches reference
                 
                 Icon sizing:
                 - Was: width={18} height={18} strokeWidth={1.8}
                 - Now: width={22} height={22} strokeWidth={1.6}
                 
                 Background color:
                 - Was: bg-[#eee6d6] (too pale)
                 - Now: bg-[#f0ebe3] (warmer, more visible)
                 
                 Text color:
                 - Was: text-[#3a3527] (dark brown)
                 - Now: text-[#4a3f33] (deeper brown, better contrast)
                 
                 Corner radius:
                 - Was: rounded-[8px]
                 - Now: rounded-[10px]
                 
                 Shadow depth:
                 - Was: shadow-[0_6px_18px_rgba(0,0,0,0.45)]
                 - Now: shadow-[0_8px_24px_rgba(0,0,0,0.5)] (stronger)
      */}
      <div
        className="animate-node-float flex h-12 w-12 items-center justify-center rounded-[10px] bg-[#f0ebe3] text-[#4a3f33] shadow-[0_8px_24px_rgba(0,0,0,0.5)] motion-reduce:animate-none"
        style={{ animationDelay: `${delay}s` }}
      >
        <Icon width={22} height={22} strokeWidth={1.6} />
      </div>
    </div>
  );
}
