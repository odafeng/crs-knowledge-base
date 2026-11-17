import { describe, expect, it } from "vitest";
import { followedUpdates, type FollowRow } from "./followed";

const row = (path: string, topic: string, date: string): FollowRow => ({
  path,
  title: path,
  date,
  topic,
  topicLabel: topic,
});

describe("the home page's followed topics, filtered in the browser", () => {
  const rows = [
    row("/papers/a/", "mCRC-MSI-H", "2026-11-13"),
    row("/papers/b/", "mCRC-RAS-wt", "2026-11-10"),
    row("/papers/c/", "mCRC-MSI-H", "2026-10-01"),
  ];

  it("keeps only followed topics, newest first, up to the limit", () => {
    expect(followedUpdates(rows, ["mCRC-MSI-H"], 5).map((r) => r.path)).toEqual(
      ["/papers/a/", "/papers/c/"],
    );
    expect(
      followedUpdates(rows, ["mCRC-MSI-H", "mCRC-RAS-wt"], 2).map(
        (r) => r.path,
      ),
    ).toEqual(["/papers/a/", "/papers/b/"]);
  });

  it("shows nothing without followed topics", () => {
    expect(followedUpdates(rows, [], 5)).toEqual([]);
  });
});
