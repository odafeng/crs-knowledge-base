// Labels, paths and presentation rules shared by the reading pages. Values mirror sitegen/config.py, urls.py and
// render.py so the Next.js pages keep the current site's URLs, wording and ordering.
import type { components } from "./api.generated";
import {
  TAXONOMY_DOMAINS,
  TAXONOMY_SUBTOPICS,
  type DomainSlug,
  type TaxonomyDomain,
  type TaxonomySubtopic,
} from "./taxonomy.generated";

export type Paper = components["schemas"]["Paper"];
export type News = components["schemas"]["News"];
export type Topic = components["schemas"]["Topic"];
export type Domain = components["schemas"]["Domain"];
export type SubtopicRef = components["schemas"]["SubtopicRef"];
export type Figure = components["schemas"]["Figure"];
export type RegulatoryRow = components["schemas"]["RegulatoryRow"];
// openapi-typescript renders the contract's "properties + anyOf [doi | pmid]" as a union with the bare {doi} and
// {pmid} branches. Every commentary the API returns has the full shape (B5 validates each one against the schema).
export type Commentary = Extract<
  NonNullable<Paper["commentary"]>[number],
  { title: string }
>;
export const commentaryOf = (paper: Paper) =>
  (paper.commentary ?? []) as Commentary[];
export type Crumbs = ReadonlyArray<readonly [name: string, path: string]>;

export const SOURCE_LABELS: Record<Paper["source"], string> = {
  curated: "人工整理",
  fulltext: "全文",
  abstract: "摘要",
  secondary: "次級來源",
};

export const COMMENTARY_LABELS: Record<string, string> = {
  Editorial: "社論",
  Comment: "評論",
  Letter: "讀者投書",
  News: "新聞",
};

export const STATUS_LABELS = {
  fda: {
    approved: "已核准",
    accelerated: "加速核准",
    none: "未核准",
    unknown: "未確認",
  },
  tfda: { approved: "已核准", none: "未核准", unknown: "未確認" },
  nhi: {
    covered: "已給付",
    conditional: "有條件給付",
    none: "未給付",
    unknown: "未確認",
  },
} as const;

export const STATUS_STYLE: Record<
  string,
  readonly [style: string, icon: string]
> = {
  approved: ["good", "check"],
  covered: ["good", "check"],
  accelerated: ["partial", "clock"],
  conditional: ["partial", "clock"],
  none: ["none", "x"],
  unknown: ["unknown", "question"],
};

export const ROBOTIC_PAGES: Record<string, string> = {
  tme: "機器手臂 TME",
  anastomosis: "機器手臂吻合",
};

export const HOME: Crumbs = [["首頁", "/"]];
export const TOPICS: Crumbs = [...HOME, ["主題", "/topics/"]];
export const MCRC: Crumbs = [
  ...TOPICS,
  ["大腸直腸腫瘤", "/specialties/colorectal-oncology/"],
  ["mCRC 治療", "/mcrc/"],
];
export const ROBOTIC: Crumbs = [
  ...TOPICS,
  ["微創手術", "/specialties/minimally-invasive-surgery/"],
  ["機器手臂手術", "/robotic/"],
];
export const NEWS: Crumbs = [...HOME, ["最新消息", "/news/"]];

export const paperPath = (paper: Pick<Paper, "slug">) =>
  `/papers/${paper.slug}/`;
export const newsPath = (item: Pick<News, "id">) => `/news/${item.id}/`;
export const topicPath = (topic: Pick<Topic, "slug">) =>
  topic.slug === "robotic" ? "/robotic/" : `/mcrc/${topic.slug}/`;
export const specialtyPath = (slug: string) => `/specialties/${slug}/`;
export const doiUrl = (doi: string) => `https://doi.org/${doi}`;

const LEGACY_TOPIC_TO_DOMAIN: Record<string, DomainSlug> = {
  "mCRC-BRAF-V600E": "colorectal-oncology",
  "mCRC-KRAS-G12C": "colorectal-oncology",
  "mCRC-MSI-H": "colorectal-oncology",
  "mCRC-HER2": "colorectal-oncology",
  "mCRC-RAS-wt": "colorectal-oncology",
  "generic-CRS": "colorectal-oncology",
  "robotic-surgery": "minimally-invasive-surgery",
};

const DOMAIN_MAP = new Map<string, TaxonomyDomain>(
  TAXONOMY_DOMAINS.map((d) => [d.slug, d]),
);

export const domainBySlug = (slug: string): TaxonomyDomain | undefined =>
  DOMAIN_MAP.get(slug);

export const subtopicsOfDomain = (slug: DomainSlug): TaxonomySubtopic[] =>
  TAXONOMY_SUBTOPICS.filter((s) => s.parentDomain === slug);

export function domainOfTopicKey(topicKey: string): DomainSlug | null {
  if (topicKey in LEGACY_TOPIC_TO_DOMAIN)
    return LEGACY_TOPIC_TO_DOMAIN[topicKey];
  if (DOMAIN_MAP.has(topicKey)) return topicKey as DomainSlug;
  return null;
}

/** Authoritative multi-domain list when the API returns paper_domains, falling back to legacy topic mapping pre-backfill. */
export function domainsOfPaper(
  paper: Pick<Paper, "topic" | "primaryDomain" | "secondaryDomains">,
): DomainSlug[] {
  const result: DomainSlug[] = [];
  if (paper.primaryDomain && DOMAIN_MAP.has(paper.primaryDomain)) {
    result.push(paper.primaryDomain as DomainSlug);
  }
  for (const sec of paper.secondaryDomains ?? []) {
    if (DOMAIN_MAP.has(sec) && !result.includes(sec as DomainSlug)) {
      result.push(sec as DomainSlug);
    }
  }
  if (result.length === 0) {
    const fallback = domainOfTopicKey(paper.topic);
    if (fallback) result.push(fallback);
  }
  return result;
}

/** Papers belonging to a specialty domain (as primary or secondary), newest first. */
export function byDomain(
  papers: readonly Paper[],
  domainSlug: string,
): Paper[] {
  return papers
    .filter((paper) => domainsOfPaper(paper).includes(domainSlug as DomainSlug))
    .sort(
      (a, b) => b.year - a.year || publishedAt(b).localeCompare(publishedAt(a)),
    );
}

/** The 6 newly added specialty domain keys seeded in app.topics (kind='domain') for forum tagging alongside the 7 legacy topics. */
export const FORUM_DOMAIN_TOPICS: ReadonlyArray<{
  key: DomainSlug;
  label: string;
}> = TAXONOMY_DOMAINS.filter(
  (d) =>
    d.slug !== "colorectal-oncology" && d.slug !== "minimally-invasive-surgery",
).map((d) => ({ key: d.slug, label: d.labelZh }));

export const isUnreviewed = (item: { review?: { status: string } }) =>
  item.review?.status === "auto";

export const headline = (item: Pick<News, "headline">) =>
  item.headline.join("");

/** sitegen titles a paper as "regimen（journal year）". */
export const paperTitle = (
  paper: Pick<Paper, "regimen" | "journal" | "year">,
) => `${paper.regimen}（${paper.journal} ${paper.year}）`;

/** What a paper card or list entry leads with: the plain-language summary when there is one (I3 #192, ADR-0025). */
export const paperLead = (
  paper: Pick<Paper, "regimen" | "result" | "summary">,
) => ({
  title: paper.summary?.title ?? paper.regimen,
  result: paper.summary?.takeaway ?? paper.result,
});

/** When a paper entered the KB: the bot's publish date, else the Paper Watch issue date, else the review date. */
export const publishedAt = (paper: Paper) =>
  paper.review?.publishedAt?.slice(0, 10) ?? paper.addedAt ?? paper.reviewedAt;

/** Newest first, as sitegen's KnowledgeBase.by_topic. */
export function byTopic(papers: readonly Paper[], topicKey: string): Paper[] {
  return papers
    .filter((paper) => paper.topic === topicKey)
    .sort(
      (a, b) => b.year - a.year || publishedAt(b).localeCompare(publishedAt(a)),
    );
}

/** Same topic first, then the newest of the rest (sitegen render._other_news). */
export function otherNews(
  all: readonly News[],
  item: News,
  papers: readonly Paper[],
): News[] {
  const topicOf = (story: News) =>
    papers.find((paper) => paper.id === story.paperId)?.topic;
  const topic = topicOf(item);
  const rest = all.filter((story) => story.id !== item.id);
  return [
    ...rest.filter((story) => topicOf(story) === topic),
    ...rest.filter((story) => topicOf(story) !== topic),
  ].slice(0, 3);
}

/**
 * Card HTML is stored as written; the current site applies two repairs when it renders (sitegen load._clean_html):
 * an empty <th> corner cell becomes <td>, and links into the repository's docs/ folder keep only their text because
 * those documents are part of the pages. The API has already sanitized the markup.
 */
export function repairCardHtml(html: string): string {
  return html
    .replace(/<th>\s*<\/th>/g, "<td></td>")
    .replace(/<a\b[^>]*href="docs\/[^"]*"[^>]*>([\s\S]*?)<\/a>/g, "$1");
}

/** Pulls a PubMed ID from legacy paper detail HTML so the facts rail can surface it cleanly. */
export function extractPmid(detailHtml: string): string | null {
  const match = detailHtml.match(
    /(?:<strong>)?PMID:?(?:<\/strong>)?\s*(\d{5,9})/i,
  );
  return match?.[1] ?? null;
}

/**
 * Strips legacy header/footer blocks from paper detail HTML that the paper page already renders in its
 * own facts rail, bottom-line block and site footer, while preserving the study body and provenance note.
 */
export function cleanPaperDetailHtml(detailHtml: string): string {
  return detailHtml
    .replace(/<div\s+class="meta">[\s\S]*?<\/div>/gi, "")
    .replace(
      /<div\s+class="note">\s*<strong>\s*Bottom Line:?\s*<\/strong>[\s\S]*?<\/div>/gi,
      "",
    )
    .replace(/<p[^>]*>\s*本頁僅供醫療專業人員教育與臨床參考[\s\S]*?<\/p>/g, "")
    .trim();
}

/** Regulatory rows of a topic, with the three notes joined the way sitegen does. */
export function regulatoryRows(topic: Topic) {
  return topic.standardOfCare.flatMap((card) =>
    (card.regulatory ?? []).map((row) => ({
      ...row,
      note: [row.fdaNote, row.tfdaNote, row.nhiNote].filter(Boolean).join("；"),
    })),
  );
}

/** NHI-covered rows that name their rule clause, newest effective date first (G12 #167). */
export function latestCoverage(topics: Topic[]) {
  return topics
    .flatMap((topic) =>
      topic.standardOfCare.flatMap((card) =>
        (card.regulatory ?? []).flatMap((row) =>
          row.nhiEffective && row.nhiClause
            ? [
                {
                  topic,
                  regimen: row.regimen,
                  nhi: row.nhi,
                  clause: row.nhiClause,
                  effective: row.nhiEffective,
                  rule: (row.sources ?? []).find((s) =>
                    s.includes("DurgFileName="),
                  ),
                },
              ]
            : [],
        ),
      ),
    )
    .sort(
      (a, b) =>
        b.effective.localeCompare(a.effective) ||
        a.regimen.localeCompare(b.regimen),
    );
}

/** A timeline finding as plain text: line breaks become "，" and tags are dropped (templates/robotic.html.j2). */
const ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: "\u00a0",
};

/** Decodes HTML character references, like Python's html.unescape for the references the data uses. */
export function decodeEntities(text: string): string {
  return text.replace(
    /&(#x[0-9a-f]+|#\d+|[a-z]+);/gi,
    (entity, name: string) => {
      if (name[0] !== "#") return ENTITIES[name.toLowerCase()] ?? entity;
      const code =
        name[1].toLowerCase() === "x"
          ? parseInt(name.slice(2), 16)
          : parseInt(name.slice(1), 10);
      return String.fromCodePoint(code);
    },
  );
}

export function findingText(html: string): string {
  return decodeEntities(
    html.replace(/<br\s*\/?>/gi, "，").replace(/<[^>]*>/g, ""),
  );
}

// --- navigation (templates/base.html.j2) ------------------------------------------------------------------------

export type Area =
  "home" | "news" | "papers" | "topics" | "subscribe" | "forum" | "about";

export const NAV: ReadonlyArray<
  readonly [label: string, href: string, area: Area]
> = [
  ["最新消息", "/news/", "news"],
  ["文獻", "/updates/", "papers"],
  ["主題", "/topics/", "topics"],
  ["訂閱", "/subscribe/", "subscribe"],
  // Members only (ADR-0022); everyone else sees how to join.
  ["論壇", "/forum/", "forum"],
  ["關於", "/about/", "about"],
];

export const TABS: ReadonlyArray<
  readonly [label: string, href: string, area: Area, icon: string]
> = [
  ["首頁", "/", "home", "home"],
  ["消息", "/news/", "news", "news"],
  ["文獻", "/updates/", "papers", "list"],
  ["主題", "/topics/", "topics", "grid"],
  ["論壇", "/forum/", "forum", "chat"],
];

/** Which navigation entry a path belongs to (the `area` rules at the top of base.html.j2). */
export function areaOf(path: string): Area | null {
  if (path === "/") return "home";
  if (path.startsWith("/news/")) return "news";
  if (path.startsWith("/updates/") || path.startsWith("/papers/"))
    return "papers";
  if (
    [
      "/topics/",
      "/specialties/",
      "/mcrc/",
      "/robotic/",
      "/drugs/",
      "/tumor-board/",
    ].some((prefix) => path.startsWith(prefix))
  )
    return "topics";
  if (path.startsWith("/subscribe/")) return "subscribe";
  if (path.startsWith("/forum/")) return "forum";
  if (path.startsWith("/about/")) return "about";
  return null;
}

// --- updates and feeds (sitegen/models.py KnowledgeBase.updates, render.py _feeds) ---------------------------

export type Update = {
  id: string;
  date: string;
  paper: Paper;
  title: string;
  summary: string;
  kind: "paper" | "commentary";
};

/** Every paper and journal commentary, newest first; ties go to the more recent trial. */
export function updates(papers: readonly Paper[]): Update[] {
  const rows: Update[] = papers.map((paper) => ({
    id: `paper/${paper.slug}`,
    date: publishedAt(paper),
    paper,
    title: paperTitle(paper),
    summary: `${paper.result}。${paper.bottomLine}`,
    kind: "paper",
  }));
  for (const paper of papers) {
    for (const c of commentaryOf(paper)) {
      rows.push({
        id: `commentary/${paper.slug}/${c.doi ?? c.title}`,
        date: c.addedAt,
        paper,
        title: `${c.journal} ${c.year ?? ""}：${c.title}`.trim(),
        summary: c.summary,
        kind: "commentary",
      });
    }
  }
  return rows.sort(
    (a, b) => b.date.localeCompare(a.date) || b.paper.year - a.paper.year,
  );
}

const daysBefore = (isoDate: string, days: number) => {
  const day = new Date(`${isoDate}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - days);
  return day.toISOString().slice(0, 10);
};

/** The home page dateline: the newest date across papers, commentary and news, and what arrived in its week. */
export function weekStats(papers: readonly Paper[], news: readonly News[]) {
  const rows = updates(papers);
  const lastUpdated =
    [...rows.map((u) => u.date), ...news.map((n) => n.publishedAt)]
      .sort()
      .at(-1) ?? "";
  const since = daysBefore(lastUpdated, 6);
  return {
    lastUpdated,
    weekPapers: rows.filter((u) => u.kind === "paper" && u.date >= since)
      .length,
    weekNews: news.filter((n) => n.publishedAt >= since).length,
  };
}

/** Omits zero-count clauses in the dateline so "本週新增 19 篇文獻" never trails an awkward "、0 則消息". */
export function formatWeekSummary({
  weekPapers,
  weekNews,
}: {
  weekPapers: number;
  weekNews: number;
}): string {
  const parts: string[] = [];
  if (weekPapers > 0) parts.push(`${weekPapers} 篇文獻`);
  if (weekNews > 0) parts.push(`${weekNews} 則消息`);
  return parts.length > 0 ? `本週新增 ${parts.join("、")}` : "最近更新";
}

/** Labels the lead feature's right-hand plate accurately when the highlighted token is a guideline version. */
export function plateKicker(value: string | number): string {
  return /^v\d/i.test(String(value).trim()) ? "指引版本" : "關鍵數字";
}

export const NEWS_FEED = "/feed/news.xml";
export const feedPath = (category: string) => `/feed/${category}.xml`;

/** The RSS feeds the site publishes: everything, news, and each topic with content. An empty topic gets none. */
export function feedList(
  papers: readonly Paper[],
  news: readonly News[],
  topics: readonly Topic[],
) {
  const feeds: { label: string; path: string }[] = [
    { label: "全部更新", path: "/rss.xml" },
  ];
  if (news.length) feeds.push({ label: "最新消息", path: NEWS_FEED });
  for (const topic of topics) {
    const has =
      papers.some((p) => p.topic === topic.key) ||
      news.some(
        (n) => papers.find((p) => p.id === n.paperId)?.topic === topic.key,
      );
    if (has) feeds.push({ label: topic.label, path: feedPath(topic.slug) });
  }
  return feeds;
}
