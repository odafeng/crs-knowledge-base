import { describe, expect, it } from "vitest";
import { buildDashboardSummary, buildRecentActivity } from "./dashboard";
import type { OwnedComment } from "./comments";
import type { OwnPost, ThreadSummary } from "./forum";

const sampleComment: OwnedComment = {
  status: "published",
  comment: {
    id: "c1",
    paperId: "niche2",
    body: "NICHE-2 的 3 年無病存活率相當亮眼。",
    anonymous: false,
    displayName: "陳醫師",
    createdAt: "2026-11-19T10:00:00Z",
    updatedAt: "2026-11-19T10:00:00Z",
    likeCount: 3,
  },
};

const sampleThread: ThreadSummary = {
  id: "t1",
  title: "BRAF V600E 臨床毒性管理",
  bodyPreview: "BREAKWATER 實務經驗交流",
  topicKey: "mCRC-BRAF-V600E",
  paperId: "bw-nejm-2025",
  anonymous: false,
  displayName: "陳醫師",
  createdAt: "2026-11-21T08:00:00Z",
  replyCount: 2,
  lastReplyAt: "2026-11-21T09:00:00Z",
  likeCount: 4,
  liked: false,
  mine: true,
  latestReply: null,
  pinned: false,
  ai: false,
};

const samplePending: OwnPost = {
  status: "pending",
  post: {
    id: "p1",
    threadId: null,
    title: "等待審核的新話題",
    body: "待維護者審核。",
    anonymous: true,
    displayName: null,
    createdAt: "2026-11-20T12:00:00Z",
    updatedAt: "2026-11-20T12:00:00Z",
    ai: false,
  },
};

describe("account dashboard helpers", () => {
  it("computes real activity counts and likes received", () => {
    const summary = buildDashboardSummary({
      followedTopics: ["mCRC-BRAF-V600E", "mCRC-MSI-H"],
      followedPapers: ["niche2"],
      comments: [sampleComment],
      ownThreads: [sampleThread],
      unpublishedForumPosts: [samplePending],
    });
    expect(summary).toEqual({
      followedTopicsCount: 2,
      followedPapersCount: 1,
      paperCommentsCount: 1,
      forumThreadsCount: 1,
      forumUnpublishedCount: 1,
      totalPostsCount: 3,
      likesReceivedCount: 7,
    });
  });

  it("merges and sorts recent activity newest-first with paper links", () => {
    const items = buildRecentActivity({
      comments: [sampleComment],
      ownThreads: [sampleThread],
      unpublishedForumPosts: [samplePending],
      papers: [
        { id: "niche2", title: "NICHE-2 (NEJM 2024)", path: "/papers/niche2/" },
      ],
      topicLabels: new Map([["mCRC-BRAF-V600E", "BRAF V600E"]]),
      limit: 5,
    });
    expect(items.map((i) => i.id)).toEqual([
      "thread:t1",
      "unpublished:p1",
      "comment:c1",
    ]);
    expect(items[0].topicLabel).toBe("BRAF V600E");
    expect(items[0].href).toBe("/forum/t1/");
    expect(items[2].href).toBe("/papers/niche2/#discussion");
    expect(items[2].title).toBe("NICHE-2 (NEJM 2024)");
  });
});
