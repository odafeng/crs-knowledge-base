import { describe, expect, it } from "vitest";
import { findEntries, searchIndex, type SearchEntry } from "./search";
import type { News, Paper, Topic } from "./site";

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

  it("matches sitegen's search.json entries: news first, then papers", () => {
    expect(index).toEqual([
      {
        path: "/news/niche2-five-year/",
        title: "NICHE-2 五年追蹤",
        meta: "最新消息 · MSI-H / dMMR",
        text: "niche-2 五年追蹤 無復發 dostarlimab 對照",
      },
      {
        path: "/papers/niche2/",
        title: "Nivolumab + Ipilimumab（NEJM 2024）",
        meta: "MSI-H / dMMR · Phase 2",
        text: "niche2 nivolumab + ipilimumab nejm 2024 msi-h / dmmr phase 2 major pathologic response 95% mpr neoadjuvant ici works",
      },
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
