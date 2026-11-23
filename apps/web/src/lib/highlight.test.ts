import { describe, expect, it } from "vitest";
import { figures } from "./highlight";

const marked = (text: string) =>
  figures(text)
    .filter((run) => run.figure)
    .map((run) => run.text);

describe("figures marks the numbers a reader scans for", () => {
  it("keeps units with their numbers", () => {
    expect(
      marked("一線 EC + mFOLFOX6 讓中位存活從 15.1 延長到 30.3 個月"),
    ).toEqual(["15.1", "30.3 個月"]);
    expect(marked("3 年 DFS 100%，HR 0.49")).toEqual(["3 年", "100%", "0.49"]);
  });

  it("leaves the detail in brackets unmarked", () => {
    expect(
      marked("HR 0.49（95% CI 0.38 to 0.63；P<0.001），12.8 個月"),
    ).toEqual(["0.49", "12.8 個月"]);
  });

  it("leaves digits inside names alone", () => {
    expect(marked("BRAF V600E 與 mFOLFOX6")).toEqual([]);
    expect(marked("PD-1、CTLA-4、5-FU 與 TAS-102")).toEqual([]);
  });

  it("leaves clinical classifiers, age ranges and randomization ratios unmarked", () => {
    expect(
      marked(
        "德國與奧地利，18-75 歲、ECOG 0-2 的 KRAS exon 2 野生型第四期大腸直腸癌病人，共 592 位。",
      ),
    ).toEqual(["592 位"]);
    expect(
      marked(
        "Grade 3 以上皮膚反應：cetuximab 組 26%、bevacizumab 組 2%；腹瀉 11% vs 14%。",
      ),
    ).toEqual(["26%", "2%", "11%", "14%"]);
    expect(
      marked("Open-label phase 3 RCT，1:1 隨機分派，RECIST 1.1。"),
    ).toEqual([]);
  });

  it("keeps every character, in order", () => {
    const text = "mOS 30.3 vs 15.1 個月，HR 0.49";
    expect(
      figures(text)
        .map((run) => run.text)
        .join(""),
    ).toBe(text);
  });
});
