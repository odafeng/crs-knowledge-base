import { describe, expect, it } from "vitest";
import { extractPaperFigures, parseArms } from "./paper-figures";

describe("parseArms", () => {
  it("extracts concise arm names and strips trailing parenthetical context", () => {
    expect(parseArms("EC+mFOLFOX6 vs SOC (1L)")).toEqual([
      "EC+mFOLFOX6",
      "SOC",
    ]);
    expect(
      parseArms(
        "Anlotinib + CapeOX vs bevacizumab + CapeOX (first-line, RAS/BRAF wt)",
      ),
    ).toEqual(["Anlotinib + CapeOX", "bevacizumab + CapeOX"]);
    expect(parseArms("EC doublet vs triplet vs control")).toBeNull();
    expect(parseArms("Pembrolizumab monotherapy")).toBeNull();
  });
});

describe("extractPaperFigures", () => {
  it("builds duration comparisons for two-arm RCTs like BREAKWATER", () => {
    const figs = extractPaperFigures({
      regimen: "EC+mFOLFOX6 vs SOC (1L)",
      endpoint: "OS",
      result: "mPFS 12.8 vs 7.1 mo; mOS 30.3 vs 15.1 mo, HR 0.49",
    });
    expect(figs).toEqual([
      {
        kind: "compare",
        armA: "EC+mFOLFOX6",
        armB: "SOC",
        rows: [
          { label: "中位無惡化存活（mPFS）", unit: "個月", a: 12.8, b: 7.1 },
          { label: "中位整體存活（mOS）", unit: "個月", a: 30.3, b: 15.1 },
        ],
      },
    ]);
  });

  it("extracts comparison bars plus forest-plot HR interval for STELLAR-303 and FRESCO", () => {
    const figs = extractPaperFigures({
      regimen: "Zanzalintinib + Atezolizumab vs Regorafenib (3L+ MSS mCRC)",
      endpoint: "OS",
      result:
        "ITT mOS 10.9 vs 9.4 mo (HR 0.80, 95% CI 0.69–0.93, p=0.0045); G3+ TRAEs 60% vs 37%",
    });
    expect(figs).toHaveLength(2);
    expect(figs[0]).toEqual({
      kind: "compare",
      armA: "Zanzalintinib + Atezolizumab",
      armB: "Regorafenib",
      rows: [
        { label: "中位整體存活（mOS）", unit: "個月", a: 10.9, b: 9.4 },
        { label: "Grade ≥3 TRAEs", unit: "%", a: 60, b: 37 },
      ],
    });
    expect(figs[1]).toMatchObject({
      kind: "interval",
      label: "OS 風險比（HR）",
      point: 0.8,
      low: 0.69,
      high: 0.93,
    });
  });

  it("extracts single-arm meters for single-arm trials without vs comparisons", () => {
    const figs = extractPaperFigures({
      regimen: "Nivolumab + low-dose ipilimumab (1L)",
      endpoint: "ORR",
      result: "ORR 69%, CR 13%, 24-mo PFS 74%, 24-mo OS 79%",
    });
    expect(figs).toEqual([
      {
        kind: "meters",
        rows: [
          { label: "客觀反應率（ORR）", percent: 69 },
          { label: "完全反應（CR）", percent: 13 },
          { label: "24-mo PFS", percent: 74 },
          { label: "24-mo OS", percent: 79 },
        ],
      },
    ]);
  });

  it("returns empty array for narrative guidelines and guards out-of-range intervals", () => {
    expect(
      extractPaperFigures({
        regimen: "NCCN Colon Cancer v3.2026（Guidelines Insights）",
        endpoint: "Guideline",
        result: "BRAF V600E 晚期治療推薦更新，新增 DPYD 檢測",
      }),
    ).toEqual([]);

    // Invalid CI (low > point) must be rejected instead of crashing intervalScale.
    expect(
      extractPaperFigures({
        regimen: "A vs B",
        endpoint: "OS",
        result: "OS HR 0.50 (95% CI 0.70-0.90)",
      }),
    ).toEqual([]);
  });
});
