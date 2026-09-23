"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";

type ChartSize = { width: number; height: number };

/** Keep the CSS-sized host mounted even when a hidden tab has no chart area. */
export function MeasuredChart({
  children,
  className,
  height,
  label,
}: {
  children: (size: ChartSize) => ReactNode;
  className?: string;
  height?: number;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<ChartSize | null>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    let active = true;
    const printMedia = window.matchMedia?.("print");
    let printing = printMedia?.matches ?? false;
    let frame: number | undefined;

    const measure = () => {
      if (!active) return;
      const { width, height } = element.getBoundingClientRect();
      const next =
        Number.isFinite(width) &&
        Number.isFinite(height) &&
        width > 0 &&
        height > 0
          ? { width, height }
          : null;
      setSize((previous) =>
        previous?.width === next?.width && previous?.height === next?.height
          ? previous
          : next,
      );
    };
    const resize = () => {
      // Print snapshots cannot wait for React's normal update batching.
      if (printing) flushSync(measure);
      else measure();
    };
    const printLayout = () => {
      flushSync(measure);
      // Some engines finish switching media styles after the print event.
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(resize);
    };
    const beforePrint = () => {
      printing = true;
      printLayout();
    };
    const afterPrint = () => {
      printing = false;
      printLayout();
    };
    const mediaChanged = (event: MediaQueryListEvent) => {
      printing = event.matches;
      printLayout();
    };

    measure();
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(element);
    window.addEventListener("resize", resize);
    window.addEventListener("beforeprint", beforePrint);
    window.addEventListener("afterprint", afterPrint);
    printMedia?.addEventListener("change", mediaChanged);

    return () => {
      active = false;
      observer?.disconnect();
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      window.removeEventListener("beforeprint", beforePrint);
      window.removeEventListener("afterprint", afterPrint);
      printMedia?.removeEventListener("change", mediaChanged);
    };
  }, []);

  return (
    <div
      ref={ref}
      className={className}
      style={{ width: "100%", minWidth: 0, height }}
      role="img"
      aria-label={label}
    >
      {size ? children(size) : null}
    </div>
  );
}
