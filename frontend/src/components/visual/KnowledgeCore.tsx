/**
 * The glowing central "Nexus core" — documents become knowledge, made
 * visible. A warm gold diamond with a soft breathing glow, sitting
 * inside two counter-rotating dashed HUD rings (gold + violet), sized
 * to match the reference's ~100px core within the KnowledgeWorld scene.
 */
export function KnowledgeCore({ size = 100 }: { size?: number }) {
  const ringOne = size - size * 0.08;
  const ringTwo = size + size * 0.36;
  const diamond = size * 0.44;

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      <svg
        className="animate-spin-slow-reverse absolute motion-reduce:animate-none"
        width={ringTwo}
        height={ringTwo}
        viewBox="0 0 100 100"
        aria-hidden="true"
        style={{ animationDuration: "25s" }}
      >
        <circle cx="50" cy="50" r="46" fill="none" stroke="var(--accent-secondary)" strokeOpacity="0.75" strokeWidth="2.2" strokeDasharray="2 5" />
      </svg>
      <svg
        className="animate-spin-slow absolute motion-reduce:animate-none"
        width={ringOne}
        height={ringOne}
        viewBox="0 0 100 100"
        aria-hidden="true"
        style={{ animationDuration: "18s" }}
      >
        <circle cx="50" cy="50" r="45" fill="none" stroke="var(--accent)" strokeOpacity="0.85" strokeWidth="2.4" strokeDasharray="1.5 4" />
      </svg>

      <div
        aria-hidden="true"
        className="animate-core-float relative rounded-[3px] motion-reduce:animate-none"
        style={{
          width: diamond,
          height: diamond,
          transform: "rotate(45deg)",
          background: "linear-gradient(135deg, var(--accent-hover), var(--accent))",
          boxShadow: `0 0 ${size * 0.4}px var(--scene-glow), 0 0 ${size * 0.16}px var(--scene-glow)`,
        }}
      />
    </div>
  );
}
