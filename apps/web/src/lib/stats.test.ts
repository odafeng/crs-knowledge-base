import { describe, expect, it } from "vitest";
import { activityRows, activitySummary } from "./stats";

const week = (date: string, activeReaders: number) => ({
  week: date,
  activeReaders,
  newAccounts: 0,
  comments: 0,
  likes: 0,
});

describe("weekly activity for the maintainer", () => {
  it("labels weeks by their Monday and scales bars to the busiest week", () => {
    const rows = activityRows([
      week("2026-11-02", 2),
      week("2026-11-09", 8),
      week("2026-11-16", 0),
    ]);
    expect(rows.map((r) => [r.label, r.bar, r.current])).toEqual([
      ["11/2 起", 25, false],
      ["11/9 起", 100, false],
      ["11/16 起（本週）", 0, true],
    ]);
  });

  it("draws no bars when nobody was active", () => {
    expect(activityRows([week("2026-11-16", 0)])[0].bar).toBe(0);
  });

  it("compares this week so far with last week", () => {
    expect(
      activitySummary([week("2026-11-09", 5), week("2026-11-16", 3)]),
    ).toBe("本週到目前有 3 位讀者留言、按讚或檢舉；上週 5 位。");
  });
});
