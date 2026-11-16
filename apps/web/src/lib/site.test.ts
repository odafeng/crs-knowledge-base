import { describe, expect, it } from "vitest";
import {
  byTopic,
  findingText,
  otherNews,
  paperTitle,
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

  it("turns a timeline finding into plain text", () => {
    expect(findingText("ROLARR<br>轉換率 NS<br/>N=471")).toBe(
      "ROLARR，轉換率 NS，N=471",
    );
    expect(
      findingText("<strong>R0</strong> &amp; CRM &lt;1 mm&#x2009;&#8805;"),
    ).toBe("R0 & CRM <1 mm ≥");
  });
});
