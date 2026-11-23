import { describe, expect, it } from "vitest";
import { buildTreatmentPathway } from "./pathway";
import type { RegulatoryRow, Topic } from "./site";

const row = (
  regimen: string,
  extra: Partial<RegulatoryRow> = {},
): RegulatoryRow => ({
  regimen,
  fda: "approved",
  tfda: "approved",
  nhi: "none",
  checkedAt: "2026-11-16",
  ...extra,
});

const topicOf = (
  label: string,
  cards: { title: string; regulatory?: RegulatoryRow[] }[],
): Pick<Topic, "label" | "standardOfCare"> => ({
  label,
  standardOfCare: cards.map((c) => ({
    title: c.title,
    icon: "",
    body_html: "",
    reviewedAt: "2026-11-16",
    refs: [],
    regulatory: c.regulatory,
  })),
});

describe("buildTreatmentPathway", () => {
  it("builds a sequential 1L -> 2L+ flow for BRAF V600E and omits non-regimen guidance cards", () => {
    const model = buildTreatmentPathway(
      topicOf("BRAF V600E", [
        { title: "第一線治療（1L）方案選擇", regulatory: [row("EC + 化療")] },
        {
          title: "第二線以上治療（2L+）",
          regulatory: [
            row("Encorafenib + cetuximab", {
              nhi: "conditional",
              nhiClause: "9.134",
            }),
          ],
        },
        { title: "關鍵原則與注意事項" },
      ]),
    );
    expect(model?.flow).toBe("sequential");
    expect(model?.stages.map((s) => [s.kind, s.id])).toEqual([
      ["first-line", "soc-0"],
      ["second-line", "soc-1"],
    ]);
  });

  it("builds a branched flow when non-metastatic neoadjuvant and metastatic 1L coexist (MSI-H)", () => {
    const model = buildTreatmentPathway(
      topicOf("MSI-H / dMMR", [
        { title: "一線免疫治療（轉移性）", regulatory: [row("Pembrolizumab")] },
        {
          title: "新輔助免疫治療（非轉移性）",
          regulatory: [row("Dostarlimab")],
        },
      ]),
    );
    expect(model?.flow).toBe("branched");
    expect(model?.stages.map((s) => s.kind)).toEqual([
      "neoadjuvant",
      "first-line",
    ]);
  });

  it("builds a single-stage flow for single-setting topics and returns null when empty", () => {
    const single = buildTreatmentPathway(
      topicOf("HER2", [
        {
          title: "HER2+ mCRC 標靶治療（後線）",
          regulatory: [row("Tucatinib + trastuzumab"), row("T-DXd")],
        },
      ]),
    );
    expect(single?.flow).toBe("single");
    expect(single?.stages[0].regimens).toHaveLength(2);
    expect(buildTreatmentPathway(topicOf("後線治療", []))).toBeNull();
  });
});
