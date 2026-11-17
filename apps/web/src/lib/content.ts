// Server-side reads for the public pages: ISR fetches against the FastAPI read API (ADR-0015, B5).
import { apiError } from "./api";
import type { DailyPick } from "./daily";
import { decodeEntities, type News, type Paper, type Topic } from "./site";

/** Matches the API's `Cache-Control: public, max-age=300`. Pages export the same value as `revalidate`. */
export const REVALIDATE_SECONDS = 300;

type Page<T> = { items: T[]; nextCursor: string | null };
type Options = { fetcher?: typeof fetch; baseUrl?: string };

function apiBase(baseUrl = process.env.GUTHUB_API_URL): string {
  if (!baseUrl)
    throw new Error(
      "GUTHUB_API_URL is not set (e.g. http://127.0.0.1:8000/api/v1)",
    );
  return baseUrl.replace(/\/$/, "");
}

async function get<T>(
  path: string,
  { fetcher = fetch, baseUrl }: Options = {},
): Promise<T | null> {
  const response = await fetcher(`${apiBase(baseUrl)}${path}`, {
    headers: { accept: "application/json" },
    next: { revalidate: REVALIDATE_SECONDS },
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
  (await listAll<Paper>("/papers", options)).map(decodePaper);
export const listNews = (options?: Options) => listAll<News>("/news", options);
export const listTopics = (options?: Options) =>
  listAll<Topic>("/topics", options);

export const getNews = (id: string, options?: Options) =>
  get<News>(`/news/${encodeURIComponent(id)}`, options);

// The site addresses papers and topics by slug, which the API cannot look up: slugs are derived from IDs
// (lower case, "_" -> "-") and cannot be reversed. The full lists are small and cached by ISR, so pages resolve
// slugs from them. If content grows, add a slug filter to the contract instead.
export async function getPaperBySlug(
  slug: string,
  options?: Options,
): Promise<Paper | null> {
  return (
    (await listPapers(options)).find((paper) => paper.slug === slug) ?? null
  );
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
  return get<DailyPick>("/daily-pick?recent=true", options).catch(() => null);
}
