// Recent plain-language news ticker on the home page (replaces the static single-line daily banner).
import type { components } from "./api.generated";
import { headline, isUnreviewed, newsPath, paperPath } from "./site";
import type { News, Paper, Topic } from "./site";

export type DailyPick = components["schemas"]["DailyPick"];

export type TickerItem = {
  id: string;
  date: string;
  title: string;
  summary: string;
  url: string;
  unreviewed: boolean;
  topicLabel?: string;
};

/** Formats "2026-11-21" as "11/21" for compact ticker badges. */
export function shortDate(iso: string): string {
  const [, month, day] = iso.split("-").map(Number);
  if (!month || !day) return iso;
  return `${month}/${day}`;
}

/**
 * Builds up to `limit` plain-language items for the home page's "近期新聞" ticker.
 * Combines recent news stories (using plain-Chinese headline + dek) and the latest daily pick
 * (preferring the paper's plain-Chinese summary when available), newest first and deduplicated by URL.
 */
export function buildRecentTicker(
  news: readonly News[],
  papers: readonly Paper[],
  topics: readonly Topic[],
  daily: DailyPick | null,
  limit = 5,
): TickerItem[] {
  const paperById = new Map(papers.map((p) => [p.id, p]));
  const paperByPath = new Map(papers.map((p) => [paperPath(p), p]));
  const topicByKey = new Map(topics.map((t) => [t.key, t]));

  const items: TickerItem[] = [];
  const seenUrls = new Set<string>();

  const pick = daily?.pick;
  if (pick) {
    const matchedPaper = paperByPath.get(pick.url);
    const topic = matchedPaper ? topicByKey.get(matchedPaper.topic) : undefined;
    const summaryTitle = matchedPaper?.summary?.title?.trim();
    const summaryTakeaway = matchedPaper?.summary?.takeaway?.trim();
    // Only include a paper pick ahead of news when it has a plain-Chinese summary (or when there are no news stories).
    const isPlainPaper = pick.kind !== "paper" || Boolean(summaryTitle);
    if (isPlainPaper || news.length === 0) {
      items.push({
        id: `pick:${pick.url}`,
        date: pick.date,
        title: summaryTitle || pick.title,
        summary: summaryTakeaway || pick.conclusion,
        url: pick.url,
        unreviewed:
          pick.unreviewed ||
          Boolean(summaryTitle && matchedPaper?.summary?.reviewedAt === null),
        topicLabel: topic?.label,
      });
      seenUrls.add(pick.url);
    }
  }

  for (const story of news) {
    const url = newsPath(story);
    if (seenUrls.has(url)) continue;
    const paper = paperById.get(story.paperId);
    const topic = paper ? topicByKey.get(paper.topic) : undefined;
    items.push({
      id: `news:${story.id}`,
      date: story.publishedAt,
      title: headline(story),
      summary: story.dek || paper?.bottomLine || "",
      url,
      unreviewed: isUnreviewed(story),
      topicLabel: topic?.label,
    });
    seenUrls.add(url);
  }

  return items
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, Math.max(1, limit));
}
