// Server-side reads for the public pages: ISR fetches against the FastAPI read API (ADR-0015, B5).
import { apiError } from "./api";
import type { DailyPick } from "./daily";
import type {
  Domain,
  News,
  NewsEvent,
  NewsSourceHealth,
  Paper,
  Topic,
} from "./site";
import {
  DOMAIN_SLUGS,
  TAXONOMY_DOMAINS,
  TAXONOMY_SUBTOPICS,
  TAXONOMY_VERSION,
  type DomainSlug,
} from "./taxonomy.generated";

/** Public content cache TTL (1 hour, K3 #253). Writes purge immediately via POST /api/revalidate using CONTENT_TAG. */
export const REVALIDATE_SECONDS = 3600;
export const CONTENT_TAG = "guthub-content";
export const CONTENT_TAGS = {
  all: CONTENT_TAG,
  papers: "papers",
  news: "news",
  newsEvents: "news-events",
  topics: "topics",
  domains: "domains",
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

export const listPapers = (options?: Options) =>
  listAll<Paper>("/papers", {
    ...options,
    tags: [CONTENT_TAGS.papers, ...(options?.tags ?? [])],
    params: { includeDetail: "false", ...(options?.params ?? {}) },
  });
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
  if (response.ok) return (await response.json()) as Paper;
  const error = await apiError(response, "無法載入內容，請稍後再試。");
  if (error.status === 404 && error.code === "not_found") {
    if (error.message === "Not Found") {
      return (
        (
          await listAll<Paper>("/papers", {
            ...options,
            tags: [CONTENT_TAGS.papers, `paper:${slug}`, ...(tags ?? [])],
          })
        ).find((paper) => paper.slug === slug) ?? null
      );
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

const VALID_DOMAIN_SLUGS = new Set<string>(DOMAIN_SLUGS);

function fallbackDomains(): Domain[] {
  return TAXONOMY_DOMAINS.map((d) => ({
    slug: d.slug,
    order: d.order,
    labelZh: d.labelZh,
    labelEn: d.labelEn,
    descriptionZh: d.descriptionZh,
    status: d.status,
    registryVersion: TAXONOMY_VERSION,
    paperCount: 0,
    subtopics: TAXONOMY_SUBTOPICS.filter((s) => s.parentDomain === d.slug).map(
      (s) => ({
        id: s.id,
        slug: s.slug,
        labelZh: s.labelZh,
        labelEn: s.labelEn,
        legacyTopicKey: s.legacyTopicKey,
        routePath: s.routePath,
        status: s.status,
      }),
    ),
  }));
}

/** Lists the 8 clinical specialty domains, falling back to the bundled registry if talking to an older API revision. */
export async function listDomains(options?: Options): Promise<Domain[]> {
  try {
    return await listAll<Domain>("/domains", {
      ...options,
      tags: [CONTENT_TAGS.domains, ...(options?.tags ?? [])],
    });
  } catch {
    return fallbackDomains();
  }
}

/** Fetches one specialty domain by slug; returns null for unknown slugs and falls back to the registry on older APIs. */
export async function getDomain(
  slug: string,
  options: Options = {},
): Promise<Domain | null> {
  if (!VALID_DOMAIN_SLUGS.has(slug)) return null;
  try {
    const domain = await get<Domain>(`/domains/${encodeURIComponent(slug)}`, {
      ...options,
      tags: [CONTENT_TAGS.domains, `domain:${slug}`, ...(options.tags ?? [])],
    });
    if (domain) return domain;
  } catch {
    // Older API revision without /domains/{slug} falls back to the versioned static registry.
  }
  return fallbackDomains().find((d) => d.slug === (slug as DomainSlug)) ?? null;
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

type NewsEventPageResponse = {
  items: NewsEvent[];
  nextCursor: string | null;
  degradedSources?: NewsSourceHealth[];
};

const NEWS_EVENT_ID = /^[a-z0-9][a-z0-9-]*$/;

/** Lists published Newsroom events and degraded source status; gracefully falls back to empty lists on older API revisions. */
export async function listNewsEvents(
  options: Options = {},
): Promise<{ items: NewsEvent[]; degradedSources: NewsSourceHealth[] }> {
  try {
    const items: NewsEvent[] = [];
    let degradedSources: NewsSourceHealth[] = [];
    let cursor: string | null = null;
    do {
      const query: URLSearchParams = new URLSearchParams({
        limit: "100",
        ...(options.params ?? {}),
        ...(cursor ? { cursor } : {}),
      });
      const page: NewsEventPageResponse | null =
        await get<NewsEventPageResponse>(`/news-events?${query}`, {
          ...options,
          tags: [CONTENT_TAGS.newsEvents, ...(options.tags ?? [])],
        });
      if (!page) return { items: [], degradedSources: [] };
      items.push(...page.items);
      if (cursor === null) degradedSources = page.degradedSources ?? [];
      cursor = page.nextCursor;
    } while (cursor);
    return { items, degradedSources };
  } catch {
    return { items: [], degradedSources: [] };
  }
}

/** Fetches one published Newsroom event by ID; returns null if missing, unverified/draft, or on an older API revision. */
export async function getNewsEvent(
  id: string,
  options: Options = {},
): Promise<NewsEvent | null> {
  if (!NEWS_EVENT_ID.test(id)) return null;
  try {
    return await get<NewsEvent>(`/news-events/${encodeURIComponent(id)}`, {
      ...options,
      tags: [
        CONTENT_TAGS.newsEvents,
        `news-event:${id}`,
        ...(options.tags ?? []),
      ],
    });
  } catch {
    return null;
  }
}
