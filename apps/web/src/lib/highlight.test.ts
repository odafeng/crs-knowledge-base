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
