"use client";

// Animated plain-language "近期新聞" ticker above the home hero: rotates gently every 6 s, pauses on hover/focus
// or user toggle, and respects prefers-reduced-motion (WCAG 2.2.2).
import Link from "next/link";
import { useEffect, useState } from "react";
import { AiChip } from "@/components/reading";
import { shortDate, type TickerItem } from "@/lib/daily";

const INTERVAL_MS = 6000;

export function RecentNewsTicker({ items }: { items: readonly TickerItem[] }) {
  const [index, setIndex] = useState(0);
  const [animated, setAnimated] = useState(false);
  const [paused, setPaused] = useState(false);
  const [interacting, setInteracting] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);

  const count = items.length;
  const safeIndex = count > 0 ? index % count : 0;
  const active = items[safeIndex];
  const canRotate = count > 1 && !paused && !interacting && !reducedMotion;

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (!canRotate) return;
    const timer = window.setInterval(() => {
      setAnimated(true);
      setIndex((prev) => (prev + 1) % count);
    }, INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [canRotate, count]);

  if (!active) return null;

  const step = (delta: number) => {
    setAnimated(true);
    setIndex((prev) => (prev + delta + count) % count);
  };

  return (
    <section
      className="daily"
      aria-labelledby="daily-title"
      onMouseEnter={() => setInteracting(true)}
      onMouseLeave={() => setInteracting(false)}
      onFocus={() => setInteracting(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setInteracting(false);
        }
      }}
    >
      <div className="container daily__inner">
        <h2 className="daily__label" id="daily-title">
          <span className="daily__dot" aria-hidden="true" />
          近期新聞
        </h2>

        <div className="daily__stage">
          <div
            className={
              animated ? "daily__main daily__main--enter" : "daily__main"
            }
            key={active.id}
          >
            <p className="daily__title">
              <time className="daily__date" dateTime={active.date}>
                {shortDate(active.date)}
              </time>
              {active.topicLabel && (
                <span className="daily__topic">{active.topicLabel}</span>
              )}
              <Link href={active.url}>{active.title}</Link>
              {active.unreviewed && <AiChip label="AI 未審" />}
            </p>
            {active.summary && (
              <p className="daily__conclusion">{active.summary}</p>
            )}
          </div>
        </div>

        {count > 1 && (
          <div
            className="daily__controls"
            role="group"
            aria-label="切換近期新聞"
          >
            <button
              type="button"
              className="daily__ctrl"
              aria-label="上一則近期新聞"
              onClick={() => step(-1)}
            >
              ‹
            </button>
            <span className="daily__counter" aria-hidden="true">
              {safeIndex + 1}/{count}
            </span>
            <button
              type="button"
              className="daily__ctrl"
              aria-label="下一則近期新聞"
              onClick={() => step(1)}
            >
              ›
            </button>
            <button
              type="button"
              className="daily__ctrl daily__ctrl--pause"
              aria-label={paused ? "繼續輪播" : "暫停輪播"}
              aria-pressed={paused}
              onClick={() => setPaused((p) => !p)}
            >
              {paused ? "▶" : "❚❚"}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
