// Server-side reads for the public pages: ISR fetches against the FastAPI read API (ADR-0015, B5).
import { apiError } from "./api";
import type { DailyPick } from "./daily";
import { decodeEntities, type News, type Paper, type Topic } from "./site";

/** Public content cache TTL (1 hour, K3 #253). Writes purge immediately via POST /api/revalidate using CONTENT_TAG. */
export const REVALIDATE_SECONDS = 3600;
export const CONTENT_TAG = "guthub-content";
export const CONTENT_TAGS = {
  all: CONTENT_TAG,
  papers: "papers",
  news: "news",
  topics: "topics",
  daily: "daily",
} as const;

type Page<T> = { items: T[]; nextCursor: string | null };
type Options = {
  fetcher?: typeof fetch;
  baseUrl?: string;
  params?: Record<string, string>;
  tags?: readonly string[];
};
const PAPER_SLUG = /^[a-z0-9][a-z0-9-]*$/;

function cacheTags(tags?: readonly string[]): string[] {
  return tags?.length ? [CONTENT_TAG, ...tags] : [CONTENT_TAG];
}

function apiBase(baseUrl = process.env.GUTHUB_API_URL): string {
  if (!baseUrl)
    throw new Error(
      "GUTHUB_API_URL is not set (e.g. http://127.0.0.1:8000/api/v1)",
    );
  return baseUrl.replace(/\/$/, "");
}

async function get<T>(
  path: string,
  { fetcher = fetch, baseUrl, tags }: Options = {},
): Promise<T | null> {
  const response = await fetcher(`${apiBase(baseUrl)}${path}`, {
    headers: { accept: "application/json" },
    next: { revalidate: REVALIDATE_SECONDS, tags: cacheTags(tags) },
  });
  if (!response.ok) {
    const error = await apiError(response, "無法載入內容，請稍後再試。");
    // Only the contract's not_found means "missing". Any other 404 (a wrong GUTHUB_API_URL, a proxy page) is an
    // error, so ISR keeps serving the last good page instead of caching a 404 for the whole revalidate window.
    if (error.status === 404 && error.code === "not_found") return null;
    throw error;
  }
  return (await response.json()) as T;
}

/** Follows nextCursor to the end. The API caps a page at 100 items. */
export async function listAll<T>(
  path: string,
  options: Options = {},
): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null = null;
  do {
    const query: URLSearchParams = new URLSearchParams({
      limit: "100",
      ...(options.params ?? {}),
      ...(cursor ? { cursor } : {}),
    });
    const page: Page<T> | null = await get<Page<T>>(
      `${path}?${query}`,
      options,
    );
    if (!page) throw new Error(`${path} returned 404`);
    items.push(...page.items);
    cursor = page.nextCursor;
  } while (cursor);
  return items;
}

// The pipeline stores these fields HTML-escaped (scripts/publish.py), so "p<0.001" arrives as "p&lt;0.001". React
// escapes text again, so they are decoded here once for every page, feed and the search index, as sitegen's loader
// does with html.unescape.
const ESCAPED = [
  "journal",
  "regimen",
  "endpoint",
  "result",
  "bottomLine",
] as const;

export function decodePaper(paper: Paper): Paper {
  const decoded = { ...paper };
  for (const field of ESCAPED)
    if (typeof paper[field] === "string")
      decoded[field] = decodeEntities(paper[field]);
  return decoded;
}

export const listPapers = async (options?: Options) =>
  (
    await listAll<Paper>("/papers", {
      ...options,
      tags: [CONTENT_TAGS.papers, ...(options?.tags ?? [])],
      params: { includeDetail: "false", ...(options?.params ?? {}) },
    })
  ).map(decodePaper);
export const listNews = (options?: Options) =>
  listAll<News>("/news", {
    ...options,
    tags: [CONTENT_TAGS.news, ...(options?.tags ?? [])],
  });
export const listTopics = (options?: Options) =>
  listAll<Topic>("/topics", {
    ...options,
    tags: [CONTENT_TAGS.topics, ...(options?.tags ?? [])],
  });

export const getNews = (id: string, options?: Options) =>
  get<News>(`/news/${encodeURIComponent(id)}`, {
    ...options,
    tags: [CONTENT_TAGS.news, `news:${id}`, ...(options?.tags ?? [])],
  });

/**
 * Fetches one full paper (including sanitized detailHtml) by slug (K4 #254).
 * Falls back to full list pagination only when talking to an older API revision
 * that has not yet deployed `/papers/by-slug/{slug}` (FastAPI's missing-route
 * 404 returns message "Not Found", whereas the endpoint returns "Paper not found").
 */
export async function getPaperBySlug(
  slug: string,
  options: Options = {},
): Promise<Paper | null> {
  if (!PAPER_SLUG.test(slug)) return null;
  const { fetcher = fetch, baseUrl, tags } = options;
  const response = await fetcher(
    `${apiBase(baseUrl)}/papers/by-slug/${encodeURIComponent(slug)}`,
    {
      headers: { accept: "application/json" },
      next: {
        revalidate: REVALIDATE_SECONDS,
        tags: cacheTags([
          CONTENT_TAGS.papers,
          `paper:${slug}`,
          ...(tags ?? []),
        ]),
      },
    },
  );
  if (response.ok) return decodePaper((await response.json()) as Paper);
  const error = await apiError(response, "無法載入內容，請稍後再試。");
  if (error.status === 404 && error.code === "not_found") {
    if (error.message === "Not Found") {
      const legacy = (
        await listAll<Paper>("/papers", {
          ...options,
          tags: [CONTENT_TAGS.papers, `paper:${slug}`, ...(tags ?? [])],
        })
      ).find((paper) => paper.slug === slug);
      return legacy ? decodePaper(legacy) : null;
    }
    return null;
  }
  throw error;
}

export async function getTopicBySlug(
  slug: string,
  options?: Options,
): Promise<Topic | null> {
  return (
    (await listTopics(options)).find((topic) => topic.slug === slug) ?? null
  );
}

/** The day's pick, or the latest earlier one; null if the API has none (or predates G2), so the home page still renders. */
export async function getDailyPick(
  options?: Options,
): Promise<DailyPick | null> {
  return get<DailyPick>("/daily-pick?recent=true", {
    ...options,
    tags: [CONTENT_TAGS.daily, ...(options?.tags ?? [])],
  }).catch(() => null);
}
