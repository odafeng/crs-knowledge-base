// Server-side reads for the public pages: ISR fetches against the FastAPI read API (ADR-0015, B5).
import { apiError } from "./api";
import type { News, Paper, Topic } from "./site";

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

export const listPapers = (options?: Options) =>
  listAll<Paper>("/papers", options);
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
