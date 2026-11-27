import { describe, expect, it } from "vitest";
import { findEntries, searchIndex, type SearchEntry } from "./search";
import type { News, NewsEvent, Paper, Topic } from "./site";

const topic = {
  key: "mCRC-MSI-H",
  slug: "msi-h",
  label: "MSI-H / dMMR",
} as unknown as Topic;
const paper = {
  id: "niche2",
  slug: "niche2",
  topic: "mCRC-MSI-H",
  regimen: "Nivolumab + Ipilimumab",
  journal: "NEJM",
  year: 2024,
  studyType: "Phase 2",
  endpoint: "Major pathologic response",
  result: "95% MPR",
  bottomLine: "Neoadjuvant ICI works",
} as unknown as Paper;
const news = {
  id: "niche2-five-year",
  paperId: "niche2",
  headline: ["NICHE-2 ", "五年追蹤"],
  dek: "無復發",
  body: [{ heading: "結果", text: "Dostarlimab 對照" }],
} as unknown as News;

describe("searchIndex", () => {
  const index = searchIndex([paper], [news], [topic]);

  it("matches sitegen's search.json entries with specialty domain labels: news first, then papers", () => {
    expect(index).toEqual([
      {
        path: "/news/niche2-five-year/",
        title: "NICHE-2 五年追蹤",
        meta: "最新消息 · MSI-H / dMMR",
        text: "niche-2 五年追蹤 無復發 大腸直腸腫瘤 colorectal oncology dostarlimab 對照",
      },
      {
        path: "/papers/niche2/",
        title: "Nivolumab + Ipilimumab（NEJM 2024）",
        meta: "MSI-H / dMMR · Phase 2",
        text: "niche2 nivolumab + ipilimumab nejm 2024 msi-h / dmmr 大腸直腸腫瘤 colorectal oncology phase 2 major pathologic response 95% mpr neoadjuvant ici works",
      },
    ]);
    expect(findEntries(index, "大腸直腸腫瘤")?.map((e) => e.path)).toEqual([
      "/news/niche2-five-year/",
      "/papers/niche2/",
    ]);
  });

  it("includes published NewsEvent briefs with specialty domain labels", () => {
    const event: NewsEvent = {
      id: "nhi-update-2026",
      category: "regulatory",
      geography: "taiwan",
      evidenceStatus: "approved",
      reviewStatus: "reviewed",
      eventDate: "2026-11-26",
      publishedAt: "2026-11-27",
      effectiveDate: "2026-12-01",
      firstPublishedAt: "2026-11-27T01:00:00Z",
      updatedAt: "2026-11-27T01:00:00Z",
      revisionNumber: 1,
      headline: "健保給付新制上路",
      whatHappened: "健保署擴大內視鏡處置給付",
      whyItMatters: "減輕病人負擔",
      clinicalRelevance: "適用門診大腸鏡瘜肉切除",
      evidenceLimitations: "限特定適應症",
      correctionNote: null,
      primaryDomain: "endoscopy",
      secondaryDomains: [],
      sources: [],
    };
    const withEvents = searchIndex([paper], [news], [topic], [event]);
    expect(findEntries(withEvents, "內視鏡")?.map((e) => e.path)).toEqual([
      "/news/events/nhi-update-2026/",
    ]);
  });
});

describe("findEntries", () => {
  const index: SearchEntry[] = [
    { path: "/a/", title: "A", meta: "", text: "niche dostarlimab" },
    { path: "/b/", title: "B", meta: "", text: "niche-2 nivolumab" },
  ];

  it("needs at least two characters before searching", () => {
    expect(findEntries(index, "")).toBeNull();
    expect(findEntries(index, "  n ")).toBeNull();
  });

  it("requires every term, case-insensitively", () => {
    expect(findEntries(index, "NICHE")?.map((e) => e.path)).toEqual([
      "/a/",
      "/b/",
    ]);
    expect(findEntries(index, "niche  Nivo")?.map((e) => e.path)).toEqual([
      "/b/",
    ]);
  });

  it("returns an empty list when nothing matches", () => {
    expect(findEntries(index, "kras")).toEqual([]);
  });
});
