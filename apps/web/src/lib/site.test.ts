import { describe, expect, it } from "vitest";
import {
  areaOf,
  byTopic,
  feedList,
  updates,
  weekStats,
  findingText,
  otherNews,
  paperTitle,
  publishedAt,
  latestCoverage,
  regulatoryRows,
  repairCardHtml,
  type News,
  type Paper,
  type Topic,
} from "./site";

const paper = (
  id: string,
  topic: Paper["topic"],
  year: number,
  publishedAt?: string,
): Paper => ({
  id,
  slug: id,
  topic,
  year,
  journal: "NEJM",
  studyType: "Phase 3 RCT",
  regimen: id,
  endpoint: "OS",
  result: "HR 0.5",
  bottomLine: "Better",
  relations: [],
  source: "curated",
  reviewedAt: "2026-01-01",
  detailHtml: "",
  ...(publishedAt
    ? { review: { status: "accepted" as const, publishedAt } }
    : {}),
});

const story = (id: string, paperId: string): News => ({
  id,
  paperId,
  publishedAt: "2026-11-01",
  headline: [id],
  dek: "",
  key: { label: "ORR", value: "50", unit: "%" },
  figures: [],
  body: [],
  review: { status: "accepted" },
});

describe("a paper's listing date", () => {
  it("prefers the bot's publish date, then the Paper Watch issue date, then the review date", () => {
    const curated = paper("a", "mCRC-MSI-H", 2026);
    expect(publishedAt(curated)).toBe("2026-01-01");
    expect(publishedAt({ ...curated, addedAt: "2025-12-01" })).toBe(
      "2025-12-01",
    );
    expect(
      publishedAt({
        ...paper("b", "mCRC-MSI-H", 2026, "2025-11-01T08:00:00Z"),
        addedAt: "2025-10-01",
      }),
    ).toBe("2025-11-01");
  });
});

describe("presentation rules mirrored from sitegen", () => {
  it("repairs card HTML the way the current site renders it", () => {
    expect(repairCardHtml("<table><tr><th> </th><th>A</th></tr></table>")).toBe(
      "<table><tr><td></td><th>A</th></tr></table>",
    );
    expect(
      repairCardHtml(
        '見 <a href="docs/trial.html">詳細整理</a>，或 <a href="https://doi.org/x">原文</a>',
      ),
    ).toBe('見 詳細整理，或 <a href="https://doi.org/x">原文</a>');
  });

  it("orders a topic's papers newest first, then by publication date", () => {
    const papers = [
      paper("old", "mCRC-MSI-H", 2020),
      paper("new-early", "mCRC-MSI-H", 2025, "2025-02-01"),
      paper("new-late", "mCRC-MSI-H", 2025, "2025-09-01"),
      paper("other", "mCRC-HER2", 2026),
    ];
    expect(byTopic(papers, "mCRC-MSI-H").map((p) => p.id)).toEqual([
      "new-late",
      "new-early",
      "old",
    ]);
  });

  it("lists other news from the same topic first", () => {
    const papers = [
      paper("a", "mCRC-MSI-H", 2025),
      paper("b", "mCRC-HER2", 2025),
    ];
    const news = [
      story("1", "b"),
      story("2", "a"),
      story("3", "a"),
      story("4", "b"),
    ];
    expect(otherNews(news, news[1], papers).map((n) => n.id)).toEqual([
      "3",
      "1",
      "4",
    ]);
  });

  it("titles papers and joins regulatory notes like the site", () => {
    expect(paperTitle({ regimen: "EC", journal: "NEJM", year: 2019 })).toBe(
      "EC（NEJM 2019）",
    );
    const topic = {
      standardOfCare: [
        {
          title: "1L",
          icon: "",
          body_html: "",
          reviewedAt: "2026-11-16",
          refs: [],
          regulatory: [
            {
              regimen: "Pembrolizumab",
              fda: "approved",
              tfda: "approved",
              nhi: "conditional",
              tfdaNote: "TFDA note",
              nhiNote: "NHI note",
              checkedAt: "2026-11-16",
            },
          ],
        },
      ],
    } as unknown as Topic;
    expect(regulatoryRows(topic)[0].note).toBe("TFDA note；NHI note");
  });

  it("lists covered rules that name a clause, newest first", () => {
    const row = (regimen: string, extra: object) => ({
      regimen,
      fda: "approved",
      tfda: "approved",
      nhi: "conditional",
      checkedAt: "2026-11-16",
      ...extra,
    });
    const topic = (key: string, rows: object[]) =>
      ({
        key,
        standardOfCare: [{ title: "", regulatory: rows }],
      }) as unknown as Topic;
    const pdf =
      "https://info.nhi.gov.tw/api/INAE3000/INAE3000S01/getPDF?DurgFileName=9.134._20260501.pdf";
    const list = latestCoverage([
      topic("msi", [
        row("Pembrolizumab", {
          nhiClause: "9.69 1.(11)",
          nhiEffective: "2025-06-01",
        }),
        row("Nivolumab", { nhi: "none" }),
      ]),
      topic("braf", [
        row("Encorafenib", {
          nhiClause: "9.134",
          nhiEffective: "2026-05-01",
          sources: ["https://data.fda.gov.tw/x", pdf],
        }),
      ]),
    ]);
    expect(list.map((r) => [r.regimen, r.effective, r.topic.key])).toEqual([
      ["Encorafenib", "2026-05-01", "braf"],
      ["Pembrolizumab", "2025-06-01", "msi"],
    ]);
    expect(list[0].rule).toBe(pdf);
    expect(list[1].rule).toBeUndefined();
  });

  it("turns a timeline finding into plain text", () => {
    expect(findingText("ROLARR<br>轉換率 NS<br/>N=471")).toBe(
      "ROLARR，轉換率 NS，N=471",
    );
    expect(
      findingText("<strong>R0</strong> &amp; CRM &lt;1 mm&#x2009;&#8805;"),
    ).toBe("R0 & CRM <1 mm ≥");
  });
});

describe("navigation, reading log and feeds mirrored from sitegen", () => {
  it("marks the navigation area by path", () => {
    expect(
      [
        "/",
        "/news/x/",
        "/papers/a/",
        "/updates/",
        "/mcrc/her2/",
        "/robotic/tme/",
        "/subscribe/",
        "/forum/x/",
        "/about/",
      ].map(areaOf),
    ).toEqual([
      "home",
      "news",
      "papers",
      "papers",
      "topics",
      "topics",
      "subscribe",
      "forum",
      "about",
    ]);
  });

  it("mixes papers and journal commentary, newest first", () => {
    const withComment: Paper = {
      ...paper("p1", "mCRC-MSI-H", 2024, "2026-01-10"),
      commentary: [
        {
          doi: "10.1/c",
          title: "Editorial",
          journal: "NEJM",
          year: 2026,
          type: "Editorial",
          summary: "A view",
          critique: false,
          newData: false,
          addedAt: "2026-03-01",
        },
      ],
    };
    const rows = updates([
      withComment,
      paper("p2", "mCRC-HER2", 2025, "2026-02-01"),
    ]);
    expect(rows.map((u) => [u.kind, u.date])).toEqual([
      ["commentary", "2026-03-01"],
      ["paper", "2026-02-01"],
      ["paper", "2026-01-10"],
    ]);
    expect(rows[0].title).toBe("NEJM 2026：Editorial");
  });

  it("counts the week ending on the newest date, seven days inclusive", () => {
    const papers = [
      paper("in", "mCRC-MSI-H", 2026, "2026-11-10"),
      paper("edge", "mCRC-MSI-H", 2026, "2026-11-04"),
      paper("out", "mCRC-MSI-H", 2026, "2026-11-03"),
    ];
    const news = [{ ...story("n", "in"), publishedAt: "2026-11-09" }];
    expect(weekStats(papers, news)).toEqual({
      lastUpdated: "2026-11-10",
      weekPapers: 2,
      weekNews: 1,
    });
  });

  it("publishes feeds for all updates, news, and only topics with content", () => {
    const topics = [
      {
        key: "mCRC-MSI-H",
        slug: "msi-h",
        label: "MSI-H / dMMR",
        roboticSections: [],
      },
      { key: "mCRC-HER2", slug: "her2", label: "HER2", roboticSections: [] },
      {
        key: "robotic-surgery",
        slug: "robotic",
        label: "機器手臂手術",
        roboticSections: [{}],
      },
    ] as unknown as Topic[];
    const feeds = feedList(
      [paper("a", "mCRC-MSI-H", 2025)],
      [story("n", "a")],
      topics,
    );
    expect(feeds.map((f) => f.path)).toEqual([
      "/rss.xml",
      "/feed/news.xml",
      "/feed/msi-h.xml",
    ]);
  });
});
