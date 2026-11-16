// Canonical URLs, robots, JSON-LD, feeds and the sitemap, ported from sitegen/urls.py, schema.py, feeds.py and
// sitemap.py. Feed IDs must never change: readers would see every old item as new.
import type { Metadata } from "next";
import {
  decodeEntities,
  isUnreviewed,
  NEWS_FEED,
  feedPath,
  newsPath,
  paperPath,
  updates,
  type Crumbs,
  type News,
  type Paper,
  type Topic,
  type Update,
} from "./site";

export const SITE_NAME = "GutHub";
export const TAGLINE = "大腸直腸外科實證更新";
export const DESCRIPTION =
  "給大腸直腸外科醫師的實證更新：追蹤 mCRC 治療與機器手臂手術的新試驗、指引與給付異動。";
const LANG = "zh-Hant-TW";
/** Stable prefix for RSS <guid>, Atom <id> and JSON Feed ids (sitegen config.FEED_TAG). Never change it. */
export const FEED_TAG = "tag:odafeng.github.io,2026";
/** Open Graph image for every page, as on the current site (templates/base.html.j2). */
export const SHARE_IMAGE = "/icons/icon-512.png";
const FEED_LIMIT = 30;

/**
 * Where canonical links, feeds and the sitemap point. Defaults to the current public site so nothing changes
 * for search engines or subscribers until the cutover (F4) sets the final origin.
 */
export function siteOrigin(): string {
  return (
    process.env.GUTHUB_SITE_ORIGIN ||
    "https://odafeng.github.io/crs-knowledge-base"
  ).replace(/\/$/, "");
}

export const absolute = (path: string) => `${siteOrigin()}${path}`;

/**
 * Until GUTHUB_SITE_PUBLIC=1 the whole Next.js site stays out of search engines, so a preview never competes
 * with the live site. Once public, only AI-unreviewed pages carry noindex (as on the current site).
 */
export function robots(indexable = true): Metadata["robots"] {
  if (process.env.GUTHUB_SITE_PUBLIC !== "1")
    return { index: false, follow: false };
  return indexable
    ? { index: true, follow: true }
    : { index: false, follow: true };
}

/** Canonical link, Open Graph and robots for one page (templates/base.html.j2 <head>). */
export function pageMetadata(
  title: string,
  description: string,
  path: string,
  {
    indexable = true,
    type = "website",
  }: { indexable?: boolean; type?: "website" | "article" } = {},
): Metadata {
  return {
    title: `${title}｜${SITE_NAME}`,
    description,
    alternates: { canonical: absolute(path) },
    robots: robots(indexable),
    openGraph: {
      type,
      siteName: SITE_NAME,
      title: `${title}｜${SITE_NAME}`,
      description,
      url: absolute(path),
      locale: "zh_TW",
      images: [absolute(SHARE_IMAGE)],
    },
    twitter: { card: "summary_large_image" },
  };
}

// --- JSON-LD (sitegen/schema.py) ------------------------------------------------------------------------------

const websiteId = () => `${absolute("/")}#website`;

const website = () => ({
  "@type": "WebSite",
  "@id": websiteId(),
  name: SITE_NAME,
  alternateName: TAGLINE,
  url: absolute("/"),
  inLanguage: LANG,
});

const breadcrumbs = (crumbs: Crumbs) => ({
  "@type": "BreadcrumbList",
  itemListElement: crumbs.map(([name, path], index) => ({
    "@type": "ListItem",
    position: index + 1,
    name,
    item: absolute(path),
  })),
});

type Graph = { "@context": string; "@graph": Record<string, unknown>[] };

export function pageJsonLd(
  name: string,
  description: string,
  path: string,
  crumbs: Crumbs,
  lastReviewed?: string,
): Graph {
  const page: Record<string, unknown> = {
    "@type": "MedicalWebPage",
    "@id": absolute(path),
    url: absolute(path),
    name,
    description,
    inLanguage: LANG,
    isPartOf: { "@id": websiteId() },
    audience: { "@type": "MedicalAudience", audienceType: "Clinician" },
  };
  if (lastReviewed) page.lastReviewed = lastReviewed;
  return {
    "@context": "https://schema.org",
    "@graph": [website(), page, breadcrumbs(crumbs)],
  };
}

const scholarly = (paper: Paper) =>
  paper.doi
    ? {
        "@type": "ScholarlyArticle",
        identifier: {
          "@type": "PropertyValue",
          propertyID: "DOI",
          value: paper.doi,
        },
        sameAs: `https://doi.org/${paper.doi}`,
        isPartOf: {
          "@type": "Periodical",
          name: decodeEntities(paper.journal),
        },
        datePublished: String(paper.year),
      }
    : undefined;

const title = (paper: Paper) =>
  `${decodeEntities(paper.regimen)}（${decodeEntities(paper.journal)} ${paper.year}）`;

export function paperJsonLd(
  paper: Paper,
  topic: Topic | undefined,
  crumbs: Crumbs,
): Graph {
  const data = pageJsonLd(
    title(paper),
    decodeEntities(paper.bottomLine),
    paperPath(paper),
    crumbs,
    paper.reviewedAt,
  );
  const page = data["@graph"][1];
  page.about = { "@type": "Thing", name: topic?.label };
  const basis = scholarly(paper);
  if (basis) page.isBasedOn = basis;
  return data;
}

export function newsJsonLd(
  item: News,
  paper: Paper | undefined,
  topic: Topic | undefined,
  crumbs: Crumbs,
): Graph {
  const path = newsPath(item);
  return {
    "@context": "https://schema.org",
    "@graph": [
      website(),
      {
        "@type": "NewsArticle",
        "@id": absolute(path),
        url: absolute(path),
        headline: item.headline.join(""),
        description: item.dek,
        datePublished: item.publishedAt,
        inLanguage: LANG,
        isPartOf: { "@id": websiteId() },
        author: { "@type": "Organization", name: SITE_NAME },
        audience: { "@type": "MedicalAudience", audienceType: "Clinician" },
        about: { "@type": "Thing", name: topic?.label },
        mainEntityOfPage: absolute(path),
        // The study by DOI when the entry has one; otherwise this site's page for the entry.
        isBasedOn:
          (paper && scholarly(paper)) ??
          (paper ? absolute(paperPath(paper)) : undefined),
      },
      breadcrumbs(crumbs),
    ],
  };
}

// --- feeds (sitegen/feeds.py and render._feeds) --------------------------------------------------------------

export type FeedItem = Omit<Update, "kind"> & { kind: Update["kind"] | "news" };
export type Feed = {
  title: string;
  description: string;
  path: string;
  items: FeedItem[];
};

/**
 * News first, then papers and commentary; one list sorted newest first (render.Site.stream). Within one day the
 * order follows the API (sitegen keeps file order), so feeds may order same-day items differently. GUIDs are
 * unaffected.
 */
export function stream(
  papers: readonly Paper[],
  news: readonly News[],
): FeedItem[] {
  const stories: FeedItem[] = news
    .map((item) => ({ item, paper: papers.find((p) => p.id === item.paperId) }))
    .filter(
      (entry): entry is { item: News; paper: Paper } =>
        entry.paper !== undefined,
    )
    .map(({ item, paper }) => ({
      id: `news/${item.id}`,
      date: item.publishedAt,
      paper,
      title: item.headline.join(""),
      summary: item.dek,
      kind: "news" as const,
    }));
  const rows = [...stories, ...updates(papers)].map((row) =>
    row.kind === "news"
      ? row
      : {
          ...row,
          title: decodeEntities(row.title),
          summary: decodeEntities(row.summary),
        },
  );
  // Array.prototype.sort is stable, like Python's sorted(..., reverse=True) on the date alone.
  return rows.sort((a, b) => b.date.localeCompare(a.date));
}

export function feeds(
  papers: readonly Paper[],
  news: readonly News[],
  topics: readonly Topic[],
): Feed[] {
  const all = stream(papers, news);
  const list: Feed[] = [
    {
      title: `${SITE_NAME}｜全部更新`,
      description: DESCRIPTION,
      path: "/rss.xml",
      items: all,
    },
  ];
  const stories = all.filter((u) => u.kind === "news");
  if (stories.length)
    list.push({
      title: `${SITE_NAME}｜最新消息`,
      description: "新文獻的新聞稿。",
      path: NEWS_FEED,
      items: stories,
    });
  for (const topic of topics.filter((t) => t.roboticSections.length === 0)) {
    const mine = all.filter((u) => u.paper.topic === topic.key);
    if (mine.length) {
      list.push({
        title: `${SITE_NAME}｜${topic.label}`,
        description: `${topic.title}的最新收錄。`,
        path: feedPath(topic.slug),
        items: mine,
      });
    }
  }
  return list.map((feed) => ({
    ...feed,
    items: feed.items.slice(0, FEED_LIMIT),
  }));
}

const guid = (item: FeedItem) => `${FEED_TAG}:${item.id}`;
const itemPath = (item: FeedItem) =>
  item.kind === "news"
    ? `/news/${item.id.slice("news/".length)}/`
    : paperPath(item.paper);

function categories(item: FeedItem, topics: readonly Topic[]): string[] {
  const topic = topics.find((t) => t.key === item.paper.topic);
  const kind = {
    news: "最新消息",
    paper: item.paper.studyType,
    commentary: "評論",
  }[item.kind];
  return [topic?.slug ?? "", topic?.label ?? "", kind];
}

/** A paper entry counts as changed when it is re-reviewed; a story or commentary does not change. */
const modified = (item: FeedItem) =>
  item.kind === "paper" && item.paper.reviewedAt > item.date
    ? item.paper.reviewedAt
    : item.date;

const xml = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const attr = (text: string) => `"${xml(text).replace(/"/g, "&quot;")}"`;
const iso = (day: string) => `${day}T00:00:00+00:00`;
const rfc822 = (day: string) => new Date(`${day}T00:00:00Z`).toUTCString();
const latest = (feed: Feed) =>
  feed.items
    .map((u) => u.date)
    .sort()
    .at(-1) ?? "1970-01-01";

export function toRss(feed: Feed, topics: readonly Topic[]): string {
  const items = feed.items
    .map(
      (u) => `    <item>
      <title>${xml(u.title)}</title>
      <link>${absolute(itemPath(u))}</link>
      <guid isPermaLink="false">${xml(guid(u))}</guid>
      <pubDate>${rfc822(u.date)}</pubDate>
      <description>${xml(u.summary)}</description>
${categories(u, topics)
  .map((c) => `      <category>${xml(c)}</category>`)
  .join("\n")}
    </item>`,
    )
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${xml(feed.title)}</title>
    <link>${absolute("/")}</link>
    <description>${xml(feed.description)}</description>
    <language>zh-TW</language>
    <lastBuildDate>${rfc822(latest(feed))}</lastBuildDate>
    <atom:link href=${attr(absolute(feed.path))} rel="self" type="application/rss+xml"/>
${items}
  </channel>
</rss>
`;
}

export function toAtom(feed: Feed, topics: readonly Topic[]): string {
  const entries = feed.items
    .map(
      (u) => `  <entry>
    <title>${xml(u.title)}</title>
    <id>${xml(guid(u))}</id>
    <link href=${attr(absolute(itemPath(u)))} rel="alternate" type="text/html"/>
    <published>${iso(u.date)}</published>
    <updated>${iso(modified(u))}</updated>
    <summary>${xml(u.summary)}</summary>
${categories(u, topics)
  .map((c) => `    <category term=${attr(c)}/>`)
  .join("\n")}
  </entry>`,
    )
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="${LANG}">
  <title>${xml(feed.title)}</title>
  <subtitle>${xml(feed.description)}</subtitle>
  <id>${FEED_TAG}:feed${feed.path}</id>
  <link href=${attr(absolute("/"))} rel="alternate" type="text/html"/>
  <link href=${attr(absolute(feed.path))} rel="self" type="application/atom+xml"/>
  <updated>${iso(latest(feed))}</updated>
  <author><name>${xml(SITE_NAME)}</name></author>
${entries}
</feed>
`;
}

export function toJsonFeed(feed: Feed, topics: readonly Topic[]): string {
  return JSON.stringify(
    {
      version: "https://jsonfeed.org/version/1.1",
      title: feed.title,
      description: feed.description,
      home_page_url: absolute("/"),
      feed_url: absolute(feed.path),
      language: LANG,
      items: feed.items.map((u) => ({
        id: guid(u),
        url: absolute(itemPath(u)),
        title: u.title,
        summary: u.summary,
        content_text: u.summary,
        date_published: iso(u.date),
        tags: categories(u, topics),
      })),
    },
    null,
    2,
  );
}

// --- sitemap and robots (sitegen/sitemap.py, render.build_site) ----------------------------------------------

/** Indexable pages in the order the current site renders them; AI-unreviewed papers and news are left out. */
export function sitemapPages(
  papers: readonly Paper[],
  news: readonly News[],
  topics: readonly Topic[],
): [path: string, modified: string | null][] {
  const all = stream(papers, news);
  const last =
    all
      .map((u) => u.date)
      .sort()
      .at(-1) ?? null;
  const mcrc = topics.filter((t) => t.roboticSections.length === 0);
  return [
    ["/", last],
    ["/news/", last],
    ["/updates/", last],
    ["/topics/", null],
    ["/mcrc/", null],
    ["/robotic/", null],
    ["/subscribe/", null],
    ["/about/", null],
    ...mcrc.map((topic): [string, string | null] => {
      const reviewed = papers
        .filter((p) => p.topic === topic.key)
        .map((p) => p.reviewedAt)
        .sort()
        .at(-1);
      return [`/mcrc/${topic.slug}/`, reviewed ?? last];
    }),
    ...topics
      .flatMap((t) => t.roboticSections)
      .map((s): [string, null] => [`/robotic/${s.slug}/`, null]),
    ...papers
      .filter((p) => !isUnreviewed(p))
      .map((p): [string, string] => [paperPath(p), p.reviewedAt]),
    ...news
      .filter((n) => !isUnreviewed(n))
      .map((n): [string, string] => [newsPath(n), n.publishedAt]),
  ];
}

export function sitemapXml(pages: readonly [string, string | null][]): string {
  const urls = pages
    .map(
      ([path, day]) =>
        `  <url><loc>${xml(absolute(path))}</loc>${day ? `<lastmod>${day}</lastmod>` : ""}</url>`,
    )
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
}

export const robotsTxt = () =>
  `User-agent: *\nAllow: /\n\nSitemap: ${absolute("/sitemap.xml")}\n`;
