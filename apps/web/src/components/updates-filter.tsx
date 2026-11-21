"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { AiChip } from "@/components/reading";
import {
  isUnreviewed,
  paperLead,
  paperPath,
  SOURCE_LABELS,
  topicPath,
  type Topic,
  type Update,
} from "@/lib/site";

export type FilterOption = {
  key: string;
  label: string;
  count: number;
};

/**
 * Client-side topic filter bar + evidence archive rows for /updates/.
 * All rows render on initial SSR with active = "all" so search engines and no-JS readers get the full list;
 * selecting a topic narrows the ledger instantaneously with roving arrow-key navigation and overflow edge-fades.
 */
export function UpdatesFilter({
  rows,
  topics,
}: {
  rows: Update[];
  topics: Topic[];
}) {
  const [active, setActive] = useState("all");
  const track = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState({ start: false, end: false });

  const topicMap = new Map(topics.map((t) => [t.key, t]));
  const topicCounts = new Map<string, number>();
  let commentaryCount = 0;
  for (const row of rows) {
    if (row.kind === "commentary") commentaryCount++;
    topicCounts.set(
      row.paper.topic,
      (topicCounts.get(row.paper.topic) ?? 0) + 1,
    );
  }

  const options: FilterOption[] = [
    { key: "all", label: "全部", count: rows.length },
    ...topics
      .filter((t) => (topicCounts.get(t.key) ?? 0) > 0)
      .map((t) => ({
        key: t.key,
        label: t.label,
        count: topicCounts.get(t.key) ?? 0,
      })),
    ...(commentaryCount > 0
      ? [{ key: "__commentary__", label: "期刊評論", count: commentaryCount }]
      : []),
  ];

  useEffect(() => {
    const node = track.current;
    if (!node) return;
    const measure = () => {
      const start = node.scrollLeft > 2;
      const end = node.scrollWidth - node.clientWidth - node.scrollLeft > 2;
      setFade((prev) =>
        prev.start === start && prev.end === end ? prev : { start, end },
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
  }, [options.length]);

  const selectedIndex = Math.max(
    0,
    options.findIndex((o) => o.key === active),
  );

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const last = options.length - 1;
    const next =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? selectedIndex === last
          ? 0
          : selectedIndex + 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? selectedIndex === 0
            ? last
            : selectedIndex - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : -1;
    if (next < 0 || !options[next]) return;
    event.preventDefault();
    const targetKey = options[next].key;
    setActive(targetKey);
    const button = track.current?.querySelector<HTMLElement>(
      `[data-filter-key="${CSS.escape(targetKey)}"]`,
    );
    button?.focus();
  }

  const visible =
    active === "all"
      ? rows
      : active === "__commentary__"
        ? rows.filter((u) => u.kind === "commentary")
        : rows.filter((u) => u.paper.topic === active);

  return (
    <div className="updates-index">
      {options.length > 2 && (
        <div
          className="filter-bar"
          data-fade-start={fade.start || undefined}
          data-fade-end={fade.end || undefined}
        >
          <div
            ref={track}
            className="filter-bar__track"
            role="group"
            aria-label="依主題篩選文獻"
          >
            {options.map((opt, index) => (
              <button
                key={opt.key}
                type="button"
                className="filter-tab"
                data-filter-key={opt.key}
                aria-pressed={active === opt.key}
                tabIndex={index === selectedIndex ? 0 : -1}
                onClick={() => setActive(opt.key)}
                onKeyDown={onKeyDown}
              >
                <span>{opt.label}</span>
                <span className="filter-tab__count">{opt.count}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      {active !== "all" && (
        <p className="updates-index__status" aria-live="polite">
          顯示 {visible.length} 則（共 {rows.length} 則）
          <button
            type="button"
            className="updates-index__reset"
            onClick={() => setActive("all")}
          >
            清除篩選
          </button>
        </p>
      )}
      {visible.length === 0 ? (
        <div className="empty-state">
          <p>這個篩選條件下目前沒有文獻。</p>
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => setActive("all")}
          >
            顯示全部文獻
          </button>
        </div>
      ) : (
        <ol className="entries entries--grid page__section">
          {visible.map((update) => {
            const { paper } = update;
            const topic = topicMap.get(paper.topic);
            return (
              <li className="entry" key={update.id}>
                {update.kind === "paper" ? (
                  <p className="eyebrow">
                    <time dateTime={update.date}>{update.date}</time>
                    {topic && (
                      <Link className="eyebrow__topic" href={topicPath(topic)}>
                        {topic.label}
                      </Link>
                    )}
                    <span>{paper.studyType}</span>
                    <span>
                      {paper.journal} {paper.year}
                    </span>
                    <span>來源：{SOURCE_LABELS[paper.source]}</span>
                    {isUnreviewed(paper) && <AiChip label="AI 未審" />}
                  </p>
                ) : (
                  <p className="eyebrow">
                    <time dateTime={update.date}>{update.date}</time>
                    {topic && (
                      <Link className="eyebrow__topic" href={topicPath(topic)}>
                        {topic.label}
                      </Link>
                    )}
                    <span>評論</span>
                  </p>
                )}
                <h2 className="entry__title">
                  <Link href={paperPath(paper)}>
                    {update.kind === "paper"
                      ? paperLead(paper).title
                      : update.title}
                  </Link>
                </h2>
                {update.kind === "paper" ? (
                  <>
                    <p className="entry__result">{paperLead(paper).result}</p>
                    <p className="entry__line">{paper.bottomLine}</p>
                  </>
                ) : (
                  <p className="entry__line">{update.summary}</p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
