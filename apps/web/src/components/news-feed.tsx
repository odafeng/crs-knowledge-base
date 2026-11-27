"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AiChip, Icon, KeyStat, Phrases } from "@/components/reading";
import {
  domainBySlug,
  domainsOfPaper,
  EVENT_CATEGORY_LABELS,
  EVENT_EVIDENCE_LABELS,
  EVENT_GEOGRAPHY_LABELS,
  EVENT_REVIEW_LABELS,
  isUnreviewed,
  isUnreviewedEvent,
  newsEventPath,
  newsPath,
  specialtyPath,
  topicPath,
  type News,
  type NewsEvent,
  type NewsSourceHealth,
  type Paper,
  type Topic,
} from "@/lib/site";
import { TAXONOMY_DOMAINS } from "@/lib/taxonomy.generated";
import styles from "./news-feed.module.css";

type TimeWindow = "all" | "7d" | "30d";
type TypeFilter = "all" | "paper_story" | NewsEvent["category"];

type UnifiedItem =
  | {
      kind: "event";
      key: string;
      publishedAt: string;
      domains: string[];
      category: NewsEvent["category"];
      event: NewsEvent;
    }
  | {
      kind: "story";
      key: string;
      publishedAt: string;
      domains: string[];
      category: "paper_story";
      story: News;
      paper: Paper | undefined;
      topic: Topic | undefined;
    };

function cutoffIso(referenceIso: string, days: number): string {
  const base = new Date(`${referenceIso}T00:00:00Z`);
  base.setUTCDate(base.getUTCDate() - days);
  return base.toISOString().slice(0, 10);
}

const EVENT_CATEGORIES: ReadonlyArray<NewsEvent["category"]> = [
  "regulatory",
  "safety",
  "guideline",
  "trial",
  "society",
  "device",
  "clinical",
];

/**
 * Unified Newsroom feed on /news/ combining event briefs (/news/events/[id]/)
 * and legacy paper-based news stories (/news/[id]/), filterable by 8 specialties,
 * event type, and time window.
 */
export function NewsFeed({
  events,
  news,
  papers,
  topics,
  degradedSources,
  todayIso,
}: {
  events: NewsEvent[];
  news: News[];
  papers: Paper[];
  topics: Topic[];
  degradedSources: NewsSourceHealth[];
  todayIso: string;
}) {
  const [domainFilter, setDomainFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [windowFilter, setWindowFilter] = useState<TimeWindow>("all");

  const unified = useMemo<UnifiedItem[]>(() => {
    const paperMap = new Map(papers.map((p) => [p.id, p]));
    const topicMap = new Map(topics.map((t) => [t.key, t]));

    const eventItems: UnifiedItem[] = events.map((event) => ({
      kind: "event",
      key: `event:${event.id}`,
      publishedAt: event.publishedAt,
      domains: [
        ...(event.primaryDomain ? [event.primaryDomain] : []),
        ...event.secondaryDomains,
      ],
      category: event.category,
      event,
    }));

    const storyItems: UnifiedItem[] = news.map((story) => {
      const paper = paperMap.get(story.paperId);
      const topic = paper ? topicMap.get(paper.topic) : undefined;
      return {
        kind: "story",
        key: `story:${story.id}`,
        publishedAt: story.publishedAt,
        domains: paper ? domainsOfPaper(paper) : [],
        category: "paper_story",
        story,
        paper,
        topic,
      };
    });

    return [...eventItems, ...storyItems].sort(
      (a, b) =>
        b.publishedAt.localeCompare(a.publishedAt) ||
        a.key.localeCompare(b.key),
    );
  }, [events, news, papers, topics]);

  const domainCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of unified) {
      for (const slug of new Set(item.domains)) {
        counts.set(slug, (counts.get(slug) ?? 0) + 1);
      }
    }
    return counts;
  }, [unified]);

  const visible = useMemo(() => {
    const since =
      windowFilter === "7d"
        ? cutoffIso(todayIso, 6)
        : windowFilter === "30d"
          ? cutoffIso(todayIso, 29)
          : null;
    return unified.filter((item) => {
      if (domainFilter !== "all" && !item.domains.includes(domainFilter))
        return false;
      if (typeFilter !== "all" && item.category !== typeFilter) return false;
      if (since && item.publishedAt < since) return false;
      return true;
    });
  }, [unified, domainFilter, typeFilter, windowFilter, todayIso]);

  const hasFilters =
    domainFilter !== "all" || typeFilter !== "all" || windowFilter !== "all";

  const resetFilters = () => {
    setDomainFilter("all");
    setTypeFilter("all");
    setWindowFilter("all");
  };

  return (
    <div>
      {degradedSources.length > 0 ? (
        <div
          className={`callout ${styles.notice}`}
          role="status"
          aria-live="polite"
        >
          <Icon name="info" />
          <p>
            部分來源更新延遲（
            {degradedSources.map((s) => s.name).join("、")}
            ），待來源恢復後將自動補齊。
          </p>
        </div>
      ) : (
        events.length === 0 && (
          <div className={`callout ${styles.notice}`} role="status">
            <Icon name="info" />
            <p>本日尚無符合發布標準的新事件快訊；下方為近期文獻整理新聞稿。</p>
          </div>
        )
      )}

      <div className={styles.controls}>
        <div className="filter-bar">
          <div
            className="filter-bar__track"
            role="group"
            aria-label="依八大專科篩選最新消息"
          >
            <button
              type="button"
              className="filter-tab"
              aria-pressed={domainFilter === "all"}
              onClick={() => setDomainFilter("all")}
            >
              <span>全部專科</span>
              <span className="filter-tab__count">{unified.length}</span>
            </button>
            {TAXONOMY_DOMAINS.map((domain) => (
              <button
                key={domain.slug}
                type="button"
                className="filter-tab"
                aria-pressed={domainFilter === domain.slug}
                onClick={() => setDomainFilter(domain.slug)}
              >
                <span>{domain.labelZh}</span>
                <span className="filter-tab__count">
                  {domainCounts.get(domain.slug) ?? 0}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className={styles.controlRow}>
          <label className={styles.selectGroup} htmlFor="news-type-filter">
            <span>事件類型</span>
            <select
              id="news-type-filter"
              className={styles.select}
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
            >
              <option value="all">全部類型</option>
              {EVENT_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {EVENT_CATEGORY_LABELS[cat]}
                </option>
              ))}
              <option value="paper_story">文獻新聞稿</option>
            </select>
          </label>

          <label className={styles.selectGroup} htmlFor="news-window-filter">
            <span>時間範圍</span>
            <select
              id="news-window-filter"
              className={styles.select}
              value={windowFilter}
              onChange={(e) => setWindowFilter(e.target.value as TimeWindow)}
            >
              <option value="all">全部時間</option>
              <option value="7d">近 7 天</option>
              <option value="30d">近 30 天</option>
            </select>
          </label>

          {hasFilters && (
            <p className="updates-index__status" aria-live="polite">
              顯示 {visible.length} 則（共 {unified.length} 則）
              <button
                type="button"
                className="updates-index__reset"
                onClick={resetFilters}
              >
                清除篩選
              </button>
            </p>
          )}
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="empty-state">
          <p>
            {hasFilters
              ? "目前篩選條件下尚無符合的消息。"
              : "目前尚無已發布的消息。"}
          </p>
          {hasFilters && (
            <button
              type="button"
              className="btn btn--secondary"
              onClick={resetFilters}
            >
              顯示全部消息
            </button>
          )}
        </div>
      ) : (
        <ol className="news-list page__section">
          {visible.map((entry) => {
            if (entry.kind === "event") {
              const { event } = entry;
              const primary = event.primaryDomain
                ? domainBySlug(event.primaryDomain)
                : undefined;
              const reviewClass =
                event.reviewStatus === "reviewed"
                  ? `${styles.badge} ${styles.badgeReviewed}`
                  : event.reviewStatus === "revised"
                    ? `${styles.badge} ${styles.badgeRevised}`
                    : "";
              return (
                <li className={styles.eventRow} key={entry.key}>
                  <p className="eyebrow">
                    <time dateTime={event.publishedAt}>
                      {event.publishedAt}
                    </time>
                    {primary && (
                      <Link
                        className="eyebrow__topic"
                        href={specialtyPath(primary.slug)}
                      >
                        {primary.labelZh}
                      </Link>
                    )}
                    <span>{EVENT_CATEGORY_LABELS[event.category]}</span>
                    <span>{EVENT_GEOGRAPHY_LABELS[event.geography]}</span>
                    {isUnreviewedEvent(event) ? (
                      <AiChip label={EVENT_REVIEW_LABELS.auto} />
                    ) : (
                      <span className={reviewClass}>
                        {EVENT_REVIEW_LABELS[event.reviewStatus]}
                      </span>
                    )}
                  </p>
                  <h2>
                    <Link href={newsEventPath(event)}>{event.headline}</Link>
                  </h2>
                  <p className="news-row__dek">{event.whatHappened}</p>
                  <p className={styles.eventRowMeta}>
                    <span className={styles.badge}>
                      {EVENT_EVIDENCE_LABELS[event.evidenceStatus]}
                    </span>
                    {event.eventDate && <span>事件日 {event.eventDate}</span>}
                    {event.effectiveDate && (
                      <span>生效日 {event.effectiveDate}</span>
                    )}
                    <span>來源 {event.sources.length} 筆</span>
                  </p>
                </li>
              );
            }

            const { story, paper, topic } = entry;
            return (
              <li className="news-row" key={entry.key}>
                <p className="eyebrow">
                  <time dateTime={story.publishedAt}>{story.publishedAt}</time>
                  {topic && (
                    <Link className="eyebrow__topic" href={topicPath(topic)}>
                      {topic.label}
                    </Link>
                  )}
                  {paper && (
                    <span>
                      {paper.journal} {paper.year}
                    </span>
                  )}
                  <AiChip label="AI 新聞稿" />
                  {isUnreviewed(story) && <AiChip label="AI 未審" />}
                </p>
                <h2 className="phrased">
                  <Link href={newsPath(story)}>
                    <Phrases item={story} />
                  </Link>
                </h2>
                <p className="news-row__dek">{story.dek}</p>
                <KeyStat item={story} className="news-row__stat" />
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
