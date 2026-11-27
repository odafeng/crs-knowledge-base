"use client";

// Richer signed-in account dashboard on /account/: profile header, real activity KPIs, recent activity timeline,
// followed papers & digest settings, followed topics, surgeon membership, notification/display preferences, and profile settings.
// All data comes exclusively from existing API endpoints; zero placeholder or synthetic counts.
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useAccount, type Account } from "@/components/account";
import { Avatar } from "@/components/avatar";
import { DisplaySettings } from "@/components/display-settings";
import { DomainChoices, TopicChoices } from "@/components/followed-topics";
import { FollowedPapers } from "@/components/paper-follows";
import { PushToggle } from "@/components/push-toggle";
import { Icon } from "@/components/reading";
import { AccountSettings } from "@/components/sign-in";
import { SurgeonMembership } from "@/components/surgeon-membership";
import { apiFetch, authEnabled } from "@/lib/auth";
import type { OwnedComment } from "@/lib/comments";
import {
  buildDashboardSummary,
  buildRecentActivity,
  type ActivityItem,
} from "@/lib/dashboard";
import {
  postDate,
  relativeTime,
  type OwnPost,
  type ThreadPage,
  type ThreadSummary,
} from "@/lib/forum";
import type { FollowedPaper, Follows } from "@/lib/paper-follows";
import { pushEnabled } from "@/lib/push";
import type { Membership } from "@/lib/surgeons";

type SignedIn = Extract<Account, { status: "signed-in" }>;
type Choice = { key: string; label: string };

export function AccountDashboard({
  topics,
  papers,
}: {
  topics: Choice[];
  papers: FollowedPaper[];
}) {
  const account = useAccount();

  if (!authEnabled || account.status !== "signed-in" || !account.displayName) {
    return (
      <div className="page__narrow">
        <AccountSettings />
      </div>
    );
  }

  return (
    <SignedInDashboard account={account} topics={topics} papers={papers} />
  );
}

function SignedInDashboard({
  account,
  topics,
  papers,
}: {
  account: SignedIn;
  topics: Choice[];
  papers: FollowedPaper[];
}) {
  const [membership, setMembership] = useState<Membership | null>(null);
  const [followedTopics, setFollowedTopics] = useState<string[]>([]);
  const [follows, setFollows] = useState<Follows | null>(null);
  const [comments, setComments] = useState<OwnedComment[]>([]);
  const [ownThreads, setOwnThreads] = useState<ThreadSummary[]>([]);
  const [unpublishedForumPosts, setUnpublishedForumPosts] = useState<OwnPost[]>(
    [],
  );
  const [activityLoaded, setActivityLoaded] = useState(false);

  const token = account.token;
  const userId = account.userId;

  useEffect(() => {
    let live = true;
    apiFetch("/me/comments?limit=100", token)
      .then((response) => (response.ok ? response.json() : null))
      .then((page: { items: OwnedComment[] } | null) => {
        if (!live) return;
        if (page) setComments(page.items);
        setActivityLoaded(true);
      })
      .catch(() => live && setActivityLoaded(true));
    return () => {
      live = false;
    };
    // Load once per account; hourly token refreshes do not change activity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const isVerified = membership?.status === "verified";

  useEffect(() => {
    if (!isVerified) return;
    let live = true;
    Promise.all([
      apiFetch("/forum/threads?limit=100", token)
        .then((r) => (r.ok ? (r.json() as Promise<ThreadPage>) : null))
        .catch(() => null),
      apiFetch("/forum/me/posts?limit=100", token)
        .then((r) =>
          r.ok ? (r.json() as Promise<{ items: OwnPost[] }>) : null,
        )
        .catch(() => null),
    ]).then(([threadPage, ownPage]) => {
      if (!live) return;
      if (threadPage) {
        const all = [...threadPage.pinned, ...threadPage.items];
        setOwnThreads(all.filter((t) => t.mine));
      }
      if (ownPage) setUnpublishedForumPosts(ownPage.items);
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, isVerified]);

  const activeThreads = useMemo(
    () => (isVerified ? ownThreads : []),
    [isVerified, ownThreads],
  );
  const activeUnpublished = useMemo(
    () => (isVerified ? unpublishedForumPosts : []),
    [isVerified, unpublishedForumPosts],
  );

  const topicLabels = useMemo(
    () => new Map(topics.map((t) => [t.key, t.label])),
    [topics],
  );

  const summary = useMemo(
    () =>
      buildDashboardSummary({
        followedTopics,
        followedPapers: follows?.papers ?? [],
        comments,
        ownThreads: activeThreads,
        unpublishedForumPosts: activeUnpublished,
      }),
    [followedTopics, follows, comments, activeThreads, activeUnpublished],
  );

  const recent = useMemo(
    () =>
      buildRecentActivity({
        comments,
        ownThreads: activeThreads,
        unpublishedForumPosts: activeUnpublished,
        papers,
        topicLabels,
        limit: 8,
      }),
    [comments, activeThreads, activeUnpublished, papers, topicLabels],
  );

  const displayName = account.displayName ?? "";

  return (
    <div className="account-dashboard">
      {/* Profile header card */}
      <section className="profile-hero" aria-label="個人檔案總覽">
        <div className="profile-hero__identity">
          <Avatar name={displayName} size="lg" />
          <div className="profile-hero__meta">
            <div className="profile-hero__name-row">
              <h2>{displayName}</h2>
              {membership?.status === "verified" && (
                <span className="status status--good">
                  <Icon name="shield" />
                  已驗證大腸直腸外科會員
                </span>
              )}
              {membership?.status === "pending" && (
                <span className="status status--partial">
                  <Icon name="clock" />
                  醫師資格審核中
                </span>
              )}
              {membership?.status === "none" && (
                <span className="chip">一般讀者帳號</span>
              )}
              {account.isAdmin && (
                <span className="chip chip--pin">維護者</span>
              )}
            </div>
            <p className="profile-hero__sub">
              {membership?.status === "verified" && membership.since && (
                <span>驗證日期：{postDate(membership.since)}</span>
              )}
              {account.email && (
                <span>登入帳號：{account.email}（不會公開）</span>
              )}
            </p>
          </div>
        </div>
        <div className="profile-hero__actions">
          {membership?.status === "verified" ? (
            <>
              <Link className="btn btn--primary" href="/forum/">
                <Icon name="chat" />
                進入醫師論壇
              </Link>
              <Link className="btn btn--secondary" href="/forum/new/">
                <Icon name="edit" />
                開新話題
              </Link>
            </>
          ) : (
            <a className="btn btn--primary" href="#surgeon-title">
              <Icon name="shield" />
              申請醫師會員
            </a>
          )}
          <Link className="btn btn--quiet" href="/updates/">
            瀏覽最新文獻
          </Link>
        </div>
        {account.isAdmin && (
          <nav className="profile-hero__admin" aria-label="維護者捷徑">
            <span className="profile-hero__admin-label">管理工具</span>
            <Link href="/admin/review/">待審內容</Link>
            <Link href="/admin/comments/">留言審核</Link>
            <Link href="/admin/forum/">論壇審核</Link>
            <Link href="/admin/surgeons/">醫師審核</Link>
            <Link href="/admin/stats/">每週活動</Link>
          </nav>
        )}
      </section>

      {/* Real activity KPI strip */}
      <section className="dash-stats" aria-label="個人使用摘要">
        <article className="dash-stat">
          <p className="dash-stat__label">追蹤文獻</p>
          <p className="dash-stat__value num">{summary.followedPapersCount}</p>
          <p className="dash-stat__hint">
            每日信箱摘要：
            {follows === null
              ? "載入中"
              : follows.commentDigest
                ? "已開啟"
                : "已關閉"}
          </p>
        </article>
        <article className="dash-stat">
          <p className="dash-stat__label">訂閱主題</p>
          <p className="dash-stat__value num">{summary.followedTopicsCount}</p>
          <p className="dash-stat__hint">共 {topics.length} 個臨床主題可追蹤</p>
        </article>
        <article className="dash-stat">
          <p className="dash-stat__label">發表內容</p>
          <p className="dash-stat__value num">{summary.totalPostsCount}</p>
          <p className="dash-stat__hint">
            {isVerified
              ? `論壇話題 ${summary.forumThreadsCount} 篇・文獻留言 ${summary.paperCommentsCount} 則`
              : `文獻留言 ${summary.paperCommentsCount} 則`}
          </p>
        </article>
        <article className="dash-stat">
          <p className="dash-stat__label">獲得讚數</p>
          <p className="dash-stat__value num">{summary.likesReceivedCount}</p>
          <p className="dash-stat__hint">
            {isVerified ? "來自文獻留言與論壇話題" : "來自文獻留言"}
          </p>
        </article>
      </section>

      {/* Two-column dashboard content */}
      <div className="dash-grid">
        <div className="dash-grid__main">
          {/* Recent activity timeline */}
          <section className="dash-card" aria-labelledby="activity-title">
            <div className="dash-card__head">
              <h2 id="activity-title">近期活動</h2>
              {recent.length > 0 && (
                <span className="chip">最近 {recent.length} 筆</span>
              )}
            </div>
            {!activityLoaded ? (
              <p className="note" aria-live="polite">
                載入活動紀錄中…
              </p>
            ) : recent.length === 0 ? (
              <div className="dash-empty">
                <p>
                  目前還沒有文獻留言或論壇貼文紀錄。閱讀新文獻時可以發表討論，或到醫師論壇發起話題。
                </p>
                <div className="comment__actions">
                  <Link className="btn btn--secondary" href="/updates/">
                    閱讀最新文獻
                  </Link>
                  {isVerified && (
                    <Link className="btn btn--quiet" href="/forum/new/">
                      發起第一個話題
                    </Link>
                  )}
                </div>
              </div>
            ) : (
              <ol className="activity-timeline">
                {recent.map((item) => (
                  <ActivityRow key={item.id} item={item} />
                ))}
              </ol>
            )}
          </section>

          <FollowedPapers papers={papers} onChange={setFollows} />
          <DomainChoices />
          <TopicChoices topics={topics} onChange={setFollowedTopics} />
        </div>

        <aside className="dash-grid__side" aria-label="會員資格與偏好設定">
          <SurgeonMembership onChange={setMembership} />

          {/* Notification & display settings summary */}
          <section className="dash-card" aria-labelledby="prefs-title">
            <div className="dash-card__head">
              <h2 id="prefs-title">通知與顯示偏好</h2>
            </div>
            <dl className="dash-summary-list">
              <div className="dash-summary-row">
                <dt>每日留言彙整信</dt>
                <dd>
                  {follows === null ? (
                    <span className="note">載入中…</span>
                  ) : follows.commentDigest ? (
                    <span className="status status--good">已開啟</span>
                  ) : (
                    <span className="chip">已關閉</span>
                  )}
                </dd>
              </div>
              <div className="dash-summary-row">
                <dt>RSS 與主題訂閱</dt>
                <dd>
                  <Link href="/subscribe/">查看訂閱網址 →</Link>
                </dd>
              </div>
            </dl>
            {pushEnabled && (
              <div className="dash-prefs-block">
                <h3>瀏覽器即時推播</h3>
                <p className="note">
                  針對此裝置設定新消息推播，不會綁定個人帳號。
                </p>
                <div className="dash-prefs-block__action">
                  <PushToggle icon={<Icon name="bell" />} />
                </div>
              </div>
            )}
            <div className="dash-prefs-block">
              <h3>閱讀外觀</h3>
              <DisplaySettings labelId="dash-text-size-label" />
            </div>
          </section>

          <AccountSettings embedded />
        </aside>
      </div>
    </div>
  );
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const kindLabel =
    item.kind === "paper-comment"
      ? "文獻留言"
      : item.kind === "forum-thread"
        ? "論壇話題"
        : "待審貼文";

  return (
    <li className="activity-item">
      <div className="activity-item__top">
        <span className="chip">{kindLabel}</span>
        {item.topicLabel && (
          <span className="chip chip--pin">{item.topicLabel}</span>
        )}
        {item.anonymous && <span className="chip">匿名</span>}
        {item.status === "pending" && (
          <span className="status status--partial">等待審核</span>
        )}
        {item.status === "hidden" && (
          <span className="status status--none">已隱藏</span>
        )}
        <time
          className="activity-item__time"
          dateTime={item.createdAt}
          title={postDate(item.createdAt)}
        >
          {relativeTime(item.createdAt)}
        </time>
      </div>
      <p className="activity-item__title">
        {item.href ? (
          <Link href={item.href}>{item.title}</Link>
        ) : (
          <span>{item.title}</span>
        )}
      </p>
      {item.excerpt && <p className="activity-item__excerpt">{item.excerpt}</p>}
      <p className="activity-item__stats">
        {item.likeCount > 0 && <span>{item.likeCount} 個讚</span>}
        {item.replyCount !== undefined && <span>{item.replyCount} 則回覆</span>}
        {item.likeCount === 0 && item.replyCount === undefined && (
          <span>{postDate(item.createdAt)}</span>
        )}
      </p>
    </li>
  );
}
