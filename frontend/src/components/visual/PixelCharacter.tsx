import type { CSSProperties } from "react";

// 12x16 pixel-art sprite, hand-authored row by row: hair, face (with
// eyes overlaid separately), a jacket with an out-stretched arm
// (holding the glowing device), and legs. One character per grid cell:
// h=hair k=skin b=jacket p=pants s=shoe .=empty.
const HUMAN_SPRITE = [
  "...hhhhhh...",
  "..hhhhhhhh..",
  ".hhhhhhhhhh.",
  ".hkkkkkkkkh.",
  ".hkkkkkkkkh.",
  "..kkkkkkkk..",
  "...bbbbbb...",
  ".bbbbbbbbbb.",
  "bbbbbbbbbbbb",
  ".bbbbbbbbbb.",
  "..bbbbbbbb..",
  "...pp..pp...",
  "...pp..pp...",
  "...pp..pp...",
  "...pp..pp...",
  "...ss..ss...",
].map((row) => row.padEnd(12, ".").slice(0, 12));

// The team's small robot companion — same grid technique, a distinct
// silhouette (round visor head, boxy body) rather than a recolored
// human. m=metal light, d=metal dark, v=visor (uses the character's
// accent color, same role hair plays on the human sprites).
const ROBOT_SPRITE = [
  "....mmmm....",
  "...mmmmmm...",
  "..mmvvvvmm..",
  "..mmvvvvmm..",
  "..mmmmmmmm..",
  "...mmmmmm...",
  "...dddddd...",
  ".dddddddddd.",
  "dddddddddddd",
  ".dddddddddd.",
  "..dddddddd..",
  "...dd..dd...",
  "...mm..mm...",
].map((row) => row.padEnd(12, ".").slice(0, 12));

const EYE_CELLS: [number, number][] = [
  [3, 3],
  [3, 8],
];

interface PixelCharacterProps {
  size?: number;
  /** Hair color (human) or visor glow color (robot) — the one thing that varies per character. */
  color?: string;
  deviceColor?: string;
  variant?: "human" | "robot";
  className?: string;
  style?: CSSProperties;
}

const SKIN = "#d9a97a";
const JACKET = "#232025";
const SHOE = "#17151a";
const METAL_LIGHT = "#c9cdd6";
const METAL_DARK = "#71757e";
const EYE = "#241f1a";

/**
 * A pixel-art team member (or, for the fourth slot, the team's robot
 * companion) — a proper multi-part sprite (hair/visor, face, jacket,
 * legs), not a flat colored block. Same hand-authored SVG-grid
 * technique as every other pixel-art element in the product (see
 * NexusMark, DocumentNode), just a bigger, multi-color grid.
 */
export function PixelCharacter({
  size = 34,
  color = "var(--accent)",
  deviceColor = "var(--accent)",
  variant = "human",
  className = "",
  style,
}: PixelCharacterProps) {
  const sprite = variant === "robot" ? ROBOT_SPRITE : HUMAN_SPRITE;
  const cols = 12;
  const rows = sprite.length;
  const height = (size / cols) * rows;

  const palette: Record<string, string> =
    variant === "robot"
      ? { m: METAL_LIGHT, d: METAL_DARK, v: color }
      : { h: color, k: SKIN, b: JACKET, p: JACKET, s: SHOE };

  return (
    <div className={`relative ${className}`} style={{ width: size, height, ...style }}>
      <svg width={size} height={height} viewBox={`0 0 ${cols} ${rows}`} aria-hidden="true" shapeRendering="crispEdges">
        {sprite.flatMap((row, y) =>
          row.split("").map((cell, x) => {
            const fill = palette[cell];
            if (!fill) return null;
            return <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill={fill} />;
          }),
        )}
        {variant === "human" &&
          EYE_CELLS.map(([y, x]) => <rect key={`eye-${x}-${y}`} x={x} y={y} width={1} height={1} fill={EYE} />)}
      </svg>
      <span
        aria-hidden="true"
        className="absolute rounded-[1px]"
        style={{
          left: size * 0.02,
          top: height * 0.5,
          width: size * 0.16,
          height: size * 0.12,
          background: deviceColor,
          boxShadow: `0 0 6px ${deviceColor}`,
        }}
      />
    </div>
  );
}
