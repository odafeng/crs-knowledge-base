"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Horizontal scroll container for wide clinical tables.
 * Adds edge-fade gradients and a narrow-screen swipe hint only when the table actually overflows
 * (adapted from the ResizeObserver + scroll edge-fade pattern).
 */
export function ScrollTable({
  label,
  hint = "左右滑動查看完整欄位",
  className = "",
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({
    overflow: false,
    start: false,
    end: false,
  });

  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    const measure = () => {
      const overflow = node.scrollWidth - node.clientWidth > 2;
      const start = node.scrollLeft > 2;
      const end = node.scrollWidth - node.clientWidth - node.scrollLeft > 2;
      setEdges((prev) =>
        prev.overflow === overflow && prev.start === start && prev.end === end
          ? prev
          : { overflow, start, end },
      );
    };
    measure();
    node.addEventListener("scroll", measure, { passive: true });
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    observer?.observe(node);
    return () => {
      node.removeEventListener("scroll", measure);
      observer?.disconnect();
    };
  }, []);

  return (
    <div
      className={`scroll-table${className ? ` ${className}` : ""}`}
      data-overflow={edges.overflow || undefined}
      data-fade-start={edges.start || undefined}
      data-fade-end={edges.end || undefined}
    >
      {edges.overflow && (
        <p className="scroll-table__hint" aria-hidden="true">
          <span>{hint}</span>
          <span className="scroll-table__arrow">{edges.end ? "→" : "←"}</span>
        </p>
      )}
      <div
        ref={scroller}
        className="table-wrap"
        tabIndex={0}
        role="region"
        aria-label={label}
      >
        {children}
      </div>
    </div>
  );
}
