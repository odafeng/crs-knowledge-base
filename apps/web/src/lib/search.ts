// The client-side search index (/search.json), built the way sitegen's _search_index builds it.
// Search stays in the browser so it also works offline from the service worker's copy.
import {
  domainBySlug,
  domainsOfPaper,
  headline,
  newsPath,
  paperPath,
  paperTitle,
  type News,
  type Paper,
  type Topic,
} from "./site";

export type SearchEntry = {
  path: string;
  title: string;
  meta: string;
  text: string;
};

function domainTerms(paper: Paper | undefined): string[] {
  if (!paper) return [];
  const terms: string[] = [];
  for (const slug of domainsOfPaper(paper)) {
    const domain = domainBySlug(slug);
    if (domain) {
      terms.push(domain.labelZh, domain.labelEn);
    }
  }
  return terms;
}

export function searchIndex(
  papers: readonly Paper[],
  news: readonly News[],
  topics: readonly Topic[],
): SearchEntry[] {
  const label = (key: string) => topics.find((t) => t.key === key)?.label;
  const paperById = (id: string) => papers.find((p) => p.id === id);
  const topicOfPaper = (id: string) => label(paperById(id)?.topic ?? "");
  return [
    ...news.map((n) => ({
      path: newsPath(n),
      title: headline(n),
      meta: `最新消息 · ${topicOfPaper(n.paperId)}`,
      text: [
        headline(n),
        n.dek,
        ...domainTerms(paperById(n.paperId)),
        ...n.body.map((s) => s.text),
      ]
        .join(" ")
        .toLowerCase(),
    })),
    ...papers.map((p) => ({
      path: paperPath(p),
      title: paperTitle(p),
      meta: `${label(p.topic)} · ${p.studyType}`,
      text: [
        p.id,
        p.regimen,
        p.journal,
        String(p.year),
        label(p.topic),
        ...domainTerms(p),
        p.studyType,
        p.endpoint,
        p.result,
        p.bottomLine,
      ]
        .join(" ")
        .toLowerCase(),
    })),
  ];
}

/** Every whitespace-separated term must appear. Returns null until the query has two characters. */
export function findEntries(
  index: readonly SearchEntry[],
  query: string,
): SearchEntry[] | null {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.join("").length < 2) return null;
  return index.filter((entry) => terms.every((t) => entry.text.includes(t)));
}
