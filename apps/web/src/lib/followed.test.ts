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

  it("matches followed specialty domains alongside fine-grained topics without duplicates", () => {
    const tagged: FollowRow[] = [
      { ...rows[0], domains: ["colorectal-oncology"] },
      { ...rows[1], domains: ["colorectal-oncology"] },
      {
        ...row("/papers/d/", "robotic-surgery", "2026-11-12"),
        domains: ["minimally-invasive-surgery", "surgical-intelligence"],
      },
    ];
    expect(
      followedUpdates(tagged, ["mCRC-MSI-H"], 5, ["surgical-intelligence"]).map(
        (r) => r.path,
      ),
    ).toEqual(["/papers/a/", "/papers/d/"]);
    expect(
      followedUpdates(tagged, ["mCRC-MSI-H"], 5, ["colorectal-oncology"]).map(
        (r) => r.path,
      ),
    ).toEqual(["/papers/a/", "/papers/b/"]);
  });
});
