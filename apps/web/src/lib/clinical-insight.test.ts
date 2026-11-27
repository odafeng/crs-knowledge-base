import { describe, expect, it } from "vitest";
import { pickDailyClinicalInsight } from "./clinical-insight";
import type { Paper, Topic } from "./site";

const topic = {
  key: "mCRC-BRAF-V600E",
  slug: "braf-v600e",
  label: "BRAF V600E",
  title: "BRAF V600E",
  paperCount: 2,
  standardOfCare: [],
  roboticSections: [],
} as unknown as Topic;

const makePaper = (
  id: string,
  reviewStatus?: "auto" | "accepted",
  reviewedSummary = false,
): Paper => ({
  id,
  slug: id.toLowerCase(),
  topic: "mCRC-BRAF-V600E",
  primaryDomain: "colorectal-oncology",
  year: 2025,
  journal: "NEJM",
  studyType: "Phase 3 RCT",
  regimen: `${id} regimen`,
  endpoint: "OS",
  result: `${id} result`,
  bottomLine: `${id} bottom line`,
  relations: [],
  source: "fulltext",
  reviewedAt: "2026-11-01",
  detailHtml: "",
  ...(reviewStatus
    ? { review: { status: reviewStatus, publishedAt: "2026-11-01" } }
    : {}),
  ...(reviewedSummary
    ? {
        summary: {
          title: `${id} 白話標題`,
          takeaway: `${id} 白話結論`,
          question: "q",
          population: "pop",
          comparison: "cmp",
          findings: ["f"],
          meaning: `${id} 臨床意義`,
          limits: ["l"],
          model: "claude-sonnet-4-6",
          writtenAt: "2026-11-01",
          reviewedAt: "2026-11-02",
        },
      }
    : {}),
});

describe("pickDailyClinicalInsight", () => {
  it("never picks AI-unreviewed papers and returns null when none are reviewed", () => {
    expect(
      pickDailyClinicalInsight(
        [makePaper("AUTO_ONLY", "auto")],
        [topic],
        "2026-11-28",
      ),
    ).toBeNull();
    expect(pickDailyClinicalInsight([], [topic], "2026-11-28")).toBeNull();
  });

  it("deterministically rotates reviewed entries by Taipei calendar date with 知識回顧 label", () => {
    const papers = [
      makePaper("P_AUTO", "auto"),
      makePaper("P1", "accepted", true),
      makePaper("P2", "accepted", true),
    ];
    const a = pickDailyClinicalInsight(papers, [topic], "2026-11-28");
    const aAgain = pickDailyClinicalInsight(papers, [topic], "2026-11-28");
    expect(a).toEqual(aAgain);
    expect(a).not.toBeNull();
    expect(a?.label).toBe("知識回顧");
    expect(a?.domainSlug).toBe("colorectal-oncology");
    expect(a?.domainLabel).toBe("大腸直腸腫瘤");
    expect(a?.reviewedAt).toBe("2026-11-01");
    expect(a?.path).toMatch(/^\/papers\/p[12]\/$/);
  });
});
