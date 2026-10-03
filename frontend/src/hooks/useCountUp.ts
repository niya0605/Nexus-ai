"use client";

import { useEffect, useRef, useState } from "react";

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Animates a number counting up from 0 to `target` once, on mount —
 * used for the XP counter.
 *
 * Always starts at 0 on both server and client render (never reads
 * `matchMedia` in the initializer) — reading it there would make the
 * client's first render disagree with the server's whenever the user
 * has reduced motion enabled, causing a hydration mismatch. Instead,
 * the reduced-motion check happens inside the effect (client-only,
 * post-hydration), which jumps to the target on the next frame instead
 * of animating — still no synchronous `setState` in the effect body
 * either way, satisfying the same rule that governs the animated path.
 */
export function useCountUp(target: number, durationMs = 900): number {
  const [value, setValue] = useState(0);
  const frameRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (prefersReducedMotion()) {
      frameRef.current = requestAnimationFrame(() => setValue(target));
      return () => {
        if (frameRef.current) cancelAnimationFrame(frameRef.current);
      };
    }

    const start = performance.now();

    function tick(now: number) {
      const progress = Math.min((now - start) / durationMs, 1);
      const eased = 1 - (1 - progress) * (1 - progress); // ease-out
      setValue(Math.round(eased * target));
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick);
      }
    }

    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, [target, durationMs]);

  return value;
}
