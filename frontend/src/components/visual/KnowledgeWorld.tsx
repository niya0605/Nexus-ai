"use client";

import { useCallback, useRef, useState, type MouseEvent } from "react";
import { KnowledgeCore } from "@/components/visual/KnowledgeCore";
import { DocumentNode, type DocumentNodeType } from "@/components/visual/DocumentNode";
import { PixelCharacter } from "@/components/visual/PixelCharacter";

// Positions and stagger delays are ported 1:1 from the reference
// composition's `.knowledge-node` (node-a..e) rules — percentages of
// the scene box, not the viewport.
const DOCUMENT_NODES: { type: DocumentNodeType; style: React.CSSProperties; delay: number; tilt: number }[] = [
  { type: "pdf", style: { left: "21%", top: "22%" }, delay: 0, tilt: -6 },
  { type: "presentation", style: { left: "68%", top: "15%" }, delay: -0.8, tilt: 4 },
  { type: "chart", style: { right: "11%", top: "42%" }, delay: -1.5, tilt: -3 },
  { type: "spreadsheet", style: { left: "8%", top: "44%" }, delay: -2.2, tilt: 5 },
  { type: "image", style: { left: "46%", top: "7%" }, delay: -3, tilt: 0 },
];

// Knowledge-graph lines, in the reference's own 700x680 viewBox — every
// line runs from the core (350, 320) out to a document node.
const CONNECTIONS = [
  { x2: 145, y2: 210 },
  { x2: 525, y2: 170 },
  { x2: 570, y2: 365 },
  { x2: 150, y2: 390 },
  { x2: 350, y2: 155 },
];

const PARTICLES = Array.from({ length: 16 }, (_, i) => ({
  left: `${(i * 41 + 6) % 100}%`,
  top: `${(i * 29) % 65}%`,
  delay: (i % 6) * 0.5,
  size: 1 + (i % 3),
  gold: i % 4 === 0,
}));

// Four team members: three with distinct hair colors, plus the team's
// small robot companion (matching the reference's fourth figure).
const CHARACTERS: { color: string; device: string; variant?: "human" | "robot" }[] = [
  { color: "#3a3128", device: "var(--accent)" }, // dark hair
  { color: "var(--scene-violet-2)", device: "var(--accent-hover)" }, // purple hair
  { color: "#e3c98f", device: "var(--accent-secondary)" }, // blonde
  { color: "var(--accent)", device: "var(--accent-hover)", variant: "robot" },
];

const STAR_BACKGROUND = [
  "radial-gradient(circle at 16% 20%, white 1px, transparent 2px)",
  "radial-gradient(circle at 78% 14%, white 1px, transparent 2px)",
  "radial-gradient(circle at 87% 52%, white 1px, transparent 2px)",
  "radial-gradient(circle at 34% 64%, white 1px, transparent 2px)",
  "radial-gradient(circle at 60% 8%, white 1px, transparent 2px)",
].join(", ");

const SCENE_BACKGROUND = [
  "radial-gradient(circle at 50% 29%, rgba(232, 185, 105, 0.22), transparent 13%)",
  "radial-gradient(circle at 55% 28%, rgba(33, 52, 92, 0.5), transparent 42%)",
  "linear-gradient(160deg, var(--scene-bg-top) 0%, var(--scene-bg-mid) 56%, var(--scene-bg-bottom) 100%)",
].join(", ");

// A unified warm-center/cool-edge color wash over the whole scene,
// blended with `overlay` — the one trick that reads as "painted
// lighting" rather than "a pile of separate CSS shapes."
const COLOR_GRADE = "radial-gradient(circle at 50% 30%, rgba(232,185,105,0.35), rgba(20,26,45,0.15) 55%, rgba(5,7,13,0.4) 100%)";

// Ground pavers, laid out as a grid so each tile can get its own
// highlight/shadow — the plaza the team is standing on.
const PAVER_COLS = 14;
const PAVER_ROWS = 3;

/**
 * The hero's cinematic "knowledge world" — one dense, continuous scene
 * rather than a sparse illustration: layered star/dot-grid atmosphere,
 * a breathing gold glow, the Nexus core, a knowledge-graph of floating
 * document nodes, a distant skyline, and a team of pixel-art characters
 * standing together at its foot. Pure CSS/SVG, no WebGL — subtle mouse
 * parallax across a few depth layers.
 */
export function KnowledgeWorld() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });

  const handleMouseMove = useCallback((event: MouseEvent<HTMLDivElement>) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setOffset({
      x: (event.clientX - rect.left) / rect.width - 0.5,
      y: (event.clientY - rect.top) / rect.height - 0.5,
    });
  }, []);

  const handleMouseLeave = useCallback(() => setOffset({ x: 0, y: 0 }), []);

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      // FIX #4: Added min-h alongside h to prevent flex parent squishing
      className="relative min-h-[500px] h-[500px] w-full overflow-hidden rounded-2xl border border-white/10 shadow-[inset_0_0_70px_rgba(0,0,0,0.35),0_25px_80px_rgba(0,0,0,0.25)] sm:h-[580px] sm:min-h-[580px]"
      style={{ backgroundImage: SCENE_BACKGROUND }}
    >
      {/* Fine dot-grid atmosphere, full bleed. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-30"
        style={{ backgroundImage: "radial-gradient(rgba(255,255,255,0.55) 0.8px, transparent 0.8px)", backgroundSize: "55px 55px" }}
      />

      {/* Static stars — furthest layer. */}
      <div
        className="pointer-events-none absolute inset-0 opacity-45 transition-transform duration-300 ease-out motion-reduce:!transform-none"
        style={{ backgroundImage: STAR_BACKGROUND, transform: `translate3d(${offset.x * -4}px, ${offset.y * -3}px, 0)` }}
      />

      {/* Animated twinkling particles — gold + white, slow drift. */}
      <div
        className="pointer-events-none absolute inset-0 transition-transform duration-300 ease-out motion-reduce:!transform-none"
        style={{ transform: `translate3d(${offset.x * -6}px, ${offset.y * -4}px, 0)` }}
      >
        {PARTICLES.map((p, i) => (
          <span
            key={i}
            aria-hidden="true"
            className="animate-twinkle absolute rounded-full motion-reduce:animate-none"
            style={{
              left: p.left,
              top: p.top,
              width: p.size,
              height: p.size,
              animationDelay: `${p.delay}s`,
              background: p.gold ? "var(--scene-glow)" : "white",
            }}
          />
        ))}
      </div>

      {/* Breathing ambient glow behind the core. */}
      <div
        aria-hidden="true"
        className="animate-core-pulse pointer-events-none absolute top-[27%] left-1/2 h-[320px] w-[320px] -translate-x-1/2 -translate-y-1/2 rounded-full blur-[14px] motion-reduce:animate-none"
        style={{ backgroundImage: "radial-gradient(circle, rgba(240,193,103,0.38), transparent 62%)" }}
      />

      {/* Slowly rotating light-ray burst radiating from the core — the
          "mysterious premium artifact" quality, not just a glow dot. */}
      <div
        aria-hidden="true"
        className="animate-spin-slow pointer-events-none absolute top-[27%] left-1/2 h-[420px] w-[420px] -translate-x-1/2 -translate-y-1/2 opacity-25 mix-blend-screen motion-reduce:animate-none"
        style={{
          backgroundImage: "conic-gradient(from 0deg, transparent 0deg, var(--scene-glow) 4deg, transparent 12deg, transparent 45deg, var(--scene-glow) 49deg, transparent 57deg, transparent 90deg, var(--scene-glow) 94deg, transparent 102deg, transparent 135deg, var(--scene-glow) 139deg, transparent 147deg, transparent 180deg, var(--scene-glow) 184deg, transparent 192deg, transparent 225deg, var(--scene-glow) 229deg, transparent 237deg, transparent 270deg, var(--scene-glow) 274deg, transparent 282deg, transparent 315deg, var(--scene-glow) 319deg, transparent 327deg, transparent 360deg)",
          WebkitMaskImage: "radial-gradient(circle, black 0%, transparent 70%)",
          maskImage: "radial-gradient(circle, black 0%, transparent 70%)",
          animationDuration: "50s",
        }}
      />

      {/* Knowledge-graph connection lines, from the core out to each document node. */}
      <svg
        className="pointer-events-none absolute inset-0 h-[75%] w-full transition-transform duration-300 ease-out motion-reduce:!transform-none"
        style={{ transform: `translate3d(${offset.x * -6}px, ${offset.y * -4}px, 0)` }}
        viewBox="0 0 700 680"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {CONNECTIONS.map((c, i) => (
          <line
            key={i}
            x1={350}
            y1={320}
            x2={c.x2}
            y2={c.y2}
            stroke="var(--accent)"
            strokeOpacity="0.45"
            strokeWidth="2.5"
            strokeDasharray="3 7"
            strokeLinecap="round"
            className="animate-line-pulse motion-reduce:animate-none"
            style={{ animationDelay: `${i * 0.4}s` }}
          />
        ))}
      </svg>

      {/* Nexus core — the scene's focal point. */}
      <div
        className="absolute top-[27%] left-1/2 -translate-x-1/2 -translate-y-1/2 transition-transform duration-300 ease-out motion-reduce:!transform-none"
        style={{ transform: `translate3d(calc(-50% + ${offset.x * 6}px), calc(-50% + ${offset.y * 4}px), 0)` }}
      >
        <KnowledgeCore size={100} />
      </div>

      {/* Floating document nodes — mid/foreground layer. */}
      <div
        className="pointer-events-none absolute inset-0 transition-transform duration-300 ease-out motion-reduce:!transform-none"
        style={{ transform: `translate3d(${offset.x * 10}px, ${offset.y * 6}px, 0)` }}
      >
        {DOCUMENT_NODES.map((node, i) => (
          <DocumentNode key={i} type={node.type} delay={node.delay} tilt={node.tilt} style={node.style} />
        ))}
      </div>

      {/* Ground plaza the team is standing on — was missing entirely
          before (characters floated with nothing beneath their feet).
          Flat tiles, lit near the core — no 3D beveling, matching the
          reference's flat illustrated-pixel-art style. */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 grid h-[64px] sm:h-[78px]" style={{ gridTemplateColumns: `repeat(${PAVER_COLS}, 1fr)`, gridTemplateRows: `repeat(${PAVER_ROWS}, 1fr)` }}>
        {Array.from({ length: PAVER_COLS * PAVER_ROWS }, (_, i) => {
          const row = Math.floor(i / PAVER_COLS);
          const distFromCenter = Math.abs(i % PAVER_COLS) - PAVER_COLS / 2;
          const lit = Math.abs(distFromCenter) < 4 - row;
          return (
            <span
              key={i}
              aria-hidden="true"
              className="border-[0.5px] border-black/40"
              style={{ background: lit ? "rgba(232,185,105,0.08)" : "transparent" }}
            />
          );
        })}
      </div>

      {/* Distant skyline. */}
      {/* FIX #1: Changed from border-t (thin lines) to gradient columns (tall bars)
                 - Removed: border-t border-accent/10, bottom-[52px]
                 - Changed: height: h → height: `${h}px`, gradient direction to 180deg
                 - Moved: bottom-[52px] → bottom-0 (flush to scene floor)
                 - Opacity: 55% → 50% (more subtle)
      */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex h-[90px] items-end justify-center gap-[5px] opacity-50 sm:h-[115px]">
        {[22, 55, 33, 77, 44, 66, 33, 55, 88, 44, 66].map((h, i) => (
          <span
            key={i}
            aria-hidden="true"
            className="relative w-[24px] sm:w-[33px]"
            style={{ height: `${h}px`, background: "linear-gradient(180deg, var(--scene-navy), #0f1118)" }}
          >
            {/* A couple of lit windows per building — tiny warm dots, the detail that makes a silhouette read as an inhabited city. */}
            {h > 40 && (
              <>
                <span aria-hidden="true" className="absolute h-[2px] w-[2px] bg-[var(--scene-glow)]" style={{ left: "30%", top: "35%", opacity: (i * 37) % 100 > 40 ? 0.7 : 0 }} />
                <span aria-hidden="true" className="absolute h-[2px] w-[2px] bg-[var(--scene-glow)]" style={{ left: "60%", top: "55%", opacity: (i * 53) % 100 > 50 ? 0.6 : 0 }} />
                <span aria-hidden="true" className="absolute h-[2px] w-[2px] bg-[var(--scene-glow)]" style={{ left: "45%", top: "20%", opacity: (i * 71) % 100 > 60 ? 0.5 : 0 }} />
              </>
            )}
          </span>
        ))}
      </div>

      {/* Team characters, standing together at the foot of the scene. */}
      {/* FIX #3: Repositioned characters above the skyline
                 - Was: bottom-[20px] (buried in skyline)
                 - Now: bottom-[95px] (75px raise)
                 - Mobile: bottom-[31px] → bottom-[120px]
      */}
      <div className="absolute inset-x-0 bottom-[95px] flex items-end justify-center gap-6 transition-transform duration-300 ease-out motion-reduce:!transform-none sm:bottom-[120px] sm:gap-9">
        {CHARACTERS.map((character, i) => (
          <PixelCharacter
            key={i}
            size={38}
            color={character.color}
            deviceColor={character.device}
            variant={character.variant}
            className="animate-character-bob motion-reduce:animate-none [filter:drop-shadow(0_4px_5px_rgba(0,0,0,0.4))]"
            style={{ animationDelay: `${-i * 0.7}s` }}
          />
        ))}
      </div>

      {/* Unified color wash on top of everything — ties the separately
          drawn shapes together into one lit scene instead of reading
          as layered flat elements. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 mix-blend-overlay" style={{ backgroundImage: COLOR_GRADE }} />
    </div>
  );
}
