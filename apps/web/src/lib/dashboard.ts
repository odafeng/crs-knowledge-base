// Pure helpers for aggregating real user activity on the /account/ dashboard.
import type { OwnedComment } from "./comments";
import type { OwnPost, ThreadSummary } from "./forum";
import type { FollowedPaper } from "./paper-follows";

export type ActivityItem = {
  id: string;
  kind: "paper-comment" | "forum-thread" | "forum-unpublished";
  title: string;
  excerpt: string;
  href: string | null;
  createdAt: string;
  status: "published" | "pending" | "hidden";
  anonymous: boolean;
  likeCount: number;
  replyCount?: number;
  topicLabel?: string;
};

export type DashboardSummary = {
  followedTopicsCount: number;
  followedPapersCount: number;
  paperCommentsCount: number;
  forumThreadsCount: number;
  forumUnpublishedCount: number;
  totalPostsCount: number;
  likesReceivedCount: number;
};

function excerptOf(text: string, max = 140): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if ([...flat].length <= max) return flat;
  return `${[...flat].slice(0, max).join("").trimEnd()}…`;
}

export function buildDashboardSummary({
  followedTopics,
  followedPapers,
  comments,
  ownThreads,
  unpublishedForumPosts,
}: {
  followedTopics: string[];
  followedPapers: string[];
  comments: OwnedComment[];
  ownThreads: ThreadSummary[];
  unpublishedForumPosts: OwnPost[];
}): DashboardSummary {
  const commentLikes = comments.reduce(
    (sum, item) => sum + item.comment.likeCount,
    0,
  );
  const threadLikes = ownThreads.reduce(
    (sum, thread) => sum + thread.likeCount,
    0,
  );
  return {
    followedTopicsCount: followedTopics.length,
    followedPapersCount: followedPapers.length,
    paperCommentsCount: comments.length,
    forumThreadsCount: ownThreads.length,
    forumUnpublishedCount: unpublishedForumPosts.length,
    totalPostsCount:
      comments.length + ownThreads.length + unpublishedForumPosts.length,
    likesReceivedCount: commentLikes + threadLikes,
  };
}

export function buildRecentActivity({
  comments,
  ownThreads,
  unpublishedForumPosts,
  papers,
  topicLabels,
  limit = 8,
}: {
  comments: OwnedComment[];
  ownThreads: ThreadSummary[];
  unpublishedForumPosts: OwnPost[];
  papers: FollowedPaper[];
  topicLabels: Map<string, string>;
  limit?: number;
}): ActivityItem[] {
  const paperMap = new Map(papers.map((paper) => [paper.id, paper]));
  const items: ActivityItem[] = [];

  for (const entry of comments) {
    const paper = paperMap.get(entry.comment.paperId);
    items.push({
      id: `comment:${entry.comment.id}`,
      kind: "paper-comment",
      title: paper ? paper.title : entry.comment.paperId,
      excerpt: excerptOf(entry.comment.body),
      href: paper ? `${paper.path}#discussion` : null,
      createdAt: entry.comment.createdAt,
      status: entry.status,
      anonymous: entry.comment.anonymous,
      likeCount: entry.comment.likeCount,
    });
  }

  for (const thread of ownThreads) {
    items.push({
      id: `thread:${thread.id}`,
      kind: "forum-thread",
      title: thread.title,
      excerpt: excerptOf(thread.bodyPreview ?? ""),
      href: `/forum/${thread.id}/`,
      createdAt: thread.createdAt,
      status: "published",
      anonymous: thread.anonymous,
      likeCount: thread.likeCount,
      replyCount: thread.replyCount,
      topicLabel: thread.topicKey
        ? topicLabels.get(thread.topicKey)
        : undefined,
    });
  }

  for (const entry of unpublishedForumPosts) {
    items.push({
      id: `unpublished:${entry.post.id}`,
      kind: "forum-unpublished",
      title: entry.post.title ?? "論壇回覆",
      excerpt: excerptOf(entry.post.body),
      href: entry.post.threadId ? `/forum/${entry.post.threadId}/` : "/forum/",
      createdAt: entry.post.createdAt,
      status: entry.status,
      anonymous: entry.post.anonymous,
      likeCount: 0,
    });
  }

  return items
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, limit);
}
