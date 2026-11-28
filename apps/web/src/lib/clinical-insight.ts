// Deterministic, rule-based Daily Clinical Insight rotation (N7 #292, ADR-0031).
// Rotates ONLY existing reviewed papers/evidence entries by Taipei calendar date.
// Never fabricates copy, skips empty domains, never counts as a new event, and never triggers notifications.
import {
  domainBySlug,
  domainsOfPaper,
  isUnreviewed,
  paperLead,
  paperPath,
  type Paper,
  type Topic,
} from "./site";
import type { DomainSlug } from "./taxonomy.generated";

export type ClinicalInsight = {
  label: "知識回顧";
  date: string;
  title: string;
  takeaway: string;
  clinicalNote: string;
  path: string;
  domainSlug: DomainSlug | null;
  domainLabel: string;
  journal: string;
  year: number;
  reviewedAt: string;
};

function dateHash(dateIso: string): number {
  let hash = 2166136261;
  for (let i = 0; i < dateIso.length; i++) {
    hash ^= dateIso.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/**
 * Picks one existing reviewed paper deterministically for `dateIso` (YYYY-MM-DD in Asia/Taipei).
 * Returns null if there are no reviewed papers, never fabricating clinical copy.
 */
export function pickDailyClinicalInsight(
  papers: readonly Paper[],
  topics: readonly Topic[],
  dateIso: string,
): ClinicalInsight | null {
  const reviewed = papers
    .filter((p) => !isUnreviewed(p) && Boolean(p.bottomLine.trim()))
    .sort((a, b) => a.id.localeCompare(b.id));
  if (reviewed.length === 0) return null;

  // Prefer entries that already have a reviewed plain-Chinese summary when available, while still rotating broadly.
  const reviewedSummaries = reviewed.filter(
    (p) => Boolean(p.summary?.title) && p.summary?.reviewedAt !== null,
  );
  const pool = reviewedSummaries.length > 0 ? reviewedSummaries : reviewed;

  const chosen = pool[dateHash(dateIso) % pool.length];
  const topicLabel =
    topics.find((t) => t.key === chosen.topic)?.label ?? chosen.topic;
  const primarySlug = domainsOfPaper(chosen)[0] ?? null;
  const domainLabel = primarySlug
    ? (domainBySlug(primarySlug)?.labelZh ?? topicLabel)
    : topicLabel;
  // The fallback pool may hold accepted papers whose AI summary is still pending review: never show that copy.
  const summary =
    chosen.summary?.reviewedAt !== null ? chosen.summary : undefined;
  const lead = paperLead({ ...chosen, summary });

  return {
    label: "知識回顧",
    date: dateIso,
    title: lead.title,
    takeaway: lead.result,
    clinicalNote: summary?.meaning?.trim() || chosen.bottomLine,
    path: paperPath(chosen),
    domainSlug: primarySlug,
    domainLabel,
    journal: chosen.journal,
    year: chosen.year,
    reviewedAt: chosen.reviewedAt,
  };
}
