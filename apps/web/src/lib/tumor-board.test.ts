import { describe, expect, it } from "vitest";
import type { Paper, Topic } from "./site";
import { boardTopics, tumorBoard } from "./tumor-board";

const paper = (id: string, extra: Partial<Paper> = {}): Paper =>
  ({
    id,
    slug: id,
    topic: "mCRC-RAS-wt",
    year: 2023,
    journal: "JAMA",
    studyType: "Phase 3 RCT",
    n: 802,
    regimen: `Regimen ${id}`,
    endpoint: "OS",
    result: `result ${id}`,
    bottomLine: `bottom ${id}`,
    doi: `10.1/${id}`,
    relations: [],
    source: "curated",
    reviewedAt: "2026-06-07",
    detailHtml: "",
    ...extra,
  }) as Paper;

const topic = {
  key: "mCRC-RAS-wt",
  slug: "ras-wt",
  label: "RAS wild-type",
  title: "RAS 野生型 mCRC",
  paperCount: 3,
  roboticSections: [],
  standardOfCare: [
    {
      title: "第一線",
      icon: "",
      body_html: "<table><tr><th></th><th>方案</th></tr></table>",
      reviewedAt: "2026-11-17",
      refs: ["paradigm", "fire3"],
      regulatory: [
        {
          regimen: "Cetuximab",
          fda: "approved",
          tfda: "approved",
          nhi: "conditional",
          nhiNote: "9.27",
          checkedAt: "2026-11-16",
          sources: ["https://example.test/9.27.pdf"],
        },
      ],
    },
    {
      title: "維持",
      icon: "",
      body_html: "<p>x</p>",
      reviewedAt: "2026-06-07",
      refs: ["fire3", "valentino"],
    },
  ],
} as unknown as Topic;

describe("tumorBoard assembles a topic's existing content, adding no numbers", () => {
  const papers = [
    paper("fire3"),
    paper("paradigm"),
    paper("valentino"),
    paper("unrelated"),
  ];
  const board = tumorBoard(topic, papers);

  it("keeps the cards with repaired HTML and their review dates", () => {
    expect(board.cards.map((c) => c.title)).toEqual(["第一線", "維持"]);
    expect(board.cards[0].html).toContain("<td></td>");
  });

  it("lists every cited trial once, in citation order, with its result and DOI", () => {
    expect(board.trials.map((t) => t.id)).toEqual([
      "paradigm",
      "fire3",
      "valentino",
    ]);
    expect(board.trials[0]).toMatchObject({
      label: "Regimen paradigm（JAMA 2023）",
      result: "result paradigm",
      doi: "10.1/paradigm",
      path: "/papers/paradigm/",
    });
  });

  it("keeps each regulatory row's sources", () => {
    expect(board.regulatory[0].sources).toEqual([
      "https://example.test/9.27.pdf",
    ]);
  });

  it("dates the sheet by its newest review or check", () => {
    expect(board.asOf).toBe("2026-11-17");
  });

  it("skips citations to papers that are no longer public", () => {
    expect(tumorBoard(topic, [paper("fire3")]).trials.map((t) => t.id)).toEqual(
      ["fire3"],
    );
  });
});

describe("boardTopics", () => {
  it("offers sheets only for topics with treatment cards", () => {
    const empty = {
      ...topic,
      key: "generic-CRS",
      standardOfCare: [],
    } as unknown as Topic;
    const robotic = {
      ...topic,
      key: "robotic-surgery",
      roboticSections: [{}],
    } as unknown as Topic;
    expect(boardTopics([topic, empty, robotic]).map((t) => t.key)).toEqual([
      "mCRC-RAS-wt",
    ]);
  });
});
