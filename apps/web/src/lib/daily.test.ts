import { describe, expect, it } from "vitest";
import { buildRecentTicker, shortDate, type DailyPick } from "./daily";
import type { News, Paper, Topic } from "./site";

const topic: Topic = {
  key: "mCRC-MSI-H",
  slug: "msi-h",
  label: "MSI-H / dMMR",
  title: "MSI-H / dMMR",
  paperCount: 1,
  standardOfCare: [],
  roboticSections: [],
};

const paper = (id: string, summary?: Paper["summary"]): Paper => ({
  id,
  slug: id,
  topic: "mCRC-MSI-H",
  year: 2026,
  journal: "Lancet",
  studyType: "Phase 2",
  regimen: `${id} regimen`,
  endpoint: "DFS",
  result: "100%",
  bottomLine: `${id} bottom line`,
  relations: [],
  source: "curated",
  reviewedAt: "2026-11-01",
  detailHtml: "",
  ...(summary ? { summary } : {}),
});

const story = (id: string, paperId: string, publishedAt: string): News => ({
  id,
  paperId,
  publishedAt,
  headline: [`${id} 標題`],
  dek: `${id} 白話摘要`,
  key: { label: "DFS", value: "100", unit: "%" },
  figures: [],
  body: [],
  review: { status: "auto" },
});

describe("recent news ticker builder", () => {
  it("formats compact dates", () => {
    expect(shortDate("2026-11-04")).toBe("11/4");
    expect(shortDate("2026-03-19")).toBe("3/19");
  });

  it("prefers plain-Chinese summary for a paper pick and deduplicates news URLs", () => {
    const p1 = paper("p1", {
      title: "術前免疫白話標題",
      question: "q",
      takeaway: "白話一句話結論",
      population: "pop",
      comparison: "cmp",
      findings: ["f"],
      meaning: "m",
      limits: ["l"],
      model: "claude-sonnet-4-6",
      writtenAt: "2026-11-20",
      reviewedAt: "2026-11-20",
    });
    const daily: DailyPick = {
      date: "2026-11-21",
      pick: {
        kind: "paper",
        title: "p1 regimen（Lancet 2026）",
        conclusion: "p1 bottom line",
        url: "/papers/p1/",
        date: "2026-11-21",
        unreviewed: false,
      },
    };
    const items = buildRecentTicker(
      [story("n1", "p1", "2026-11-13"), story("n2", "p1", "2026-11-04")],
      [p1],
      [topic],
      daily,
      5,
    );
    expect(items.map((i) => [i.date, i.title, i.summary, i.url])).toEqual([
      ["2026-11-21", "術前免疫白話標題", "白話一句話結論", "/papers/p1/"],
      ["2026-11-13", "n1 標題", "n1 白話摘要", "/news/n1/"],
      ["2026-11-04", "n2 標題", "n2 白話摘要", "/news/n2/"],
    ]);
    expect(items[0].topicLabel).toBe("MSI-H / dMMR");
  });

  it("does not duplicate a news story that is also the daily pick", () => {
    const daily: DailyPick = {
      date: "2026-11-13",
      pick: {
        kind: "news",
        title: "n1 標題",
        conclusion: "n1 白話摘要",
        url: "/news/n1/",
        date: "2026-11-13",
        unreviewed: true,
      },
    };
    const items = buildRecentTicker(
      [story("n1", "p1", "2026-11-13"), story("n2", "p1", "2026-11-04")],
      [paper("p1")],
      [topic],
      daily,
    );
    expect(items.map((i) => i.url)).toEqual(["/news/n1/", "/news/n2/"]);
  });

  it("skips a raw-regimen paper pick without a Chinese summary when plain-Chinese news exist", () => {
    const daily: DailyPick = {
      date: "2026-11-21",
      pick: {
        kind: "paper",
        title: "Anlotinib + CapeOX vs bevacizumab + CapeOX（STTT 2026）",
        conclusion: "ANCHOR technical bottom line",
        url: "/papers/anchor/",
        date: "2026-11-21",
        unreviewed: false,
      },
    };
    const items = buildRecentTicker(
      [story("n1", "p1", "2026-11-13")],
      [paper("anchor"), paper("p1")],
      [topic],
      daily,
    );
    expect(items.map((i) => i.url)).toEqual(["/news/n1/"]);
  });
});
