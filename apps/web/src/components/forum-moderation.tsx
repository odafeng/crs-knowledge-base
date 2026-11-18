"use client";

// The maintainer's forum moderation (H7 #129, ADR-0022): the queue of first posts and reported posts, and every
// thread to pin or hide. The API decides who may moderate (app.accounts.is_admin); the maintainer does not need to be
// a forum member. Authors stay hidden unless the maintainer asks with a reason, and every action is recorded.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAccount, type Account } from "@/components/account";
import { apiFetch, authEnabled } from "@/lib/auth";
import { retryAfterOf } from "@/lib/comments";
import { authorName, errorMessage, postDate } from "@/lib/forum";
import type { components } from "@/lib/api.generated";

type QueueItem = components["schemas"]["ForumModerationItem"];
type ThreadItem =
  components["schemas"]["ForumAdminThreadPage"]["items"][number];
type PostRecord = components["schemas"]["ForumPostRecord"];
type Identity = components["schemas"]["AuthorIdentity"];
type SignedIn = Extract<Account, { status: "signed-in" }>;

const STATUS = { pending: "等待審核", published: "公開中", hidden: "已隱藏" };

export function ForumModeration() {
  const account = useAccount();
  if (!authEnabled) return <p>登入功能尚未開放。</p>;
  if (account.status === "loading") return <p aria-live="polite">載入中…</p>;
  if (account.status === "unavailable")
    return <p role="alert">目前無法連線到帳號服務，請稍後再試。</p>;
  if (account.status === "signed-out") {
    return (
      <p>
        請先<Link href="/login/?next=%2Fadmin%2Fforum%2F">登入</Link>。
      </p>
    );
  }
  if (!account.isAdmin) return <p role="alert">需要管理者權限。</p>;
  return <Moderation account={account} />;
}

function useList<T>(path: string, token: string, version: number) {
  const [items, setItems] = useState<T[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    apiFetch(path, token)
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then(
        (page: { items: T[] }) => live && setItems(page.items),
        () => live && setFailed(true),
      );
    return () => {
      live = false;
    };
    // Refetch on changes, not on hourly token refreshes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, version]);
  return { items, failed };
}

function Moderation({ account }: { account: SignedIn }) {
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  const queue = useList<QueueItem>(
    "/admin/forum-posts?limit=100",
    account.token,
    version,
  );
  const threads = useList<ThreadItem>(
    "/admin/forum-threads?limit=100",
    account.token,
    version,
  );
  return (
    <>
      <section aria-labelledby="forum-queue">
        <h2 id="forum-queue">等待處理的貼文</h2>
        {queue.failed && <p role="alert">{errorMessage(null, "load")}</p>}
        {!queue.failed && queue.items === null && (
          <p aria-live="polite">載入佇列中…</p>
        )}
        {queue.items?.length === 0 && <p>目前沒有等待處理的貼文。</p>}
        {queue.items && queue.items.length > 0 && (
          <ul className="comment-list" aria-label="等待處理的貼文">
            {queue.items.map((item) => (
              <Moderated
                key={item.post.id}
                post={item.post}
                status={item.status}
                context={
                  item.threadTitle ? `回覆「${item.threadTitle}」` : "新話題"
                }
                reports={item.reports}
                token={account.token}
                onDone={refresh}
              />
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="forum-all">
        <h2 id="forum-all">所有話題</h2>
        {threads.failed && <p role="alert">{errorMessage(null, "load")}</p>}
        {threads.items?.length === 0 && <p>還沒有話題。</p>}
        {threads.items && threads.items.length > 0 && (
          <ul className="comment-list" aria-label="所有話題">
            {threads.items.map((item) => (
              <Moderated
                key={item.post.id}
                post={item.post}
                status={item.status}
                context={`${item.replyCount} 則回覆`}
                pinned={item.pinned}
                token={account.token}
                onDone={refresh}
              />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function Moderated({
  post,
  status,
  context,
  reports = [],
  pinned,
  token,
  onDone,
}: {
  post: PostRecord;
  status: QueueItem["status"];
  context: string;
  reports?: QueueItem["reports"];
  pinned?: boolean;
  token: string;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  // Queue items and thread rows can show the same post; keep their field IDs apart.
  const id = `forum-reason-${pinned === undefined ? "q" : "t"}-${post.id}`;

  async function send(
    path: string,
    init: RequestInit,
  ): Promise<Response | null> {
    if (!reason.trim()) {
      setMessage("請先寫下處理原因，會記錄在稽核紀錄裡。");
      return null;
    }
    setBusy(true);
    const response = await apiFetch(path, token, init).catch(() => null);
    setBusy(false);
    if (!response?.ok) {
      setMessage(
        response?.status === 409
          ? "這篇貼文已經是這個狀態。"
          : errorMessage(
              response?.status ?? null,
              "edit",
              retryAfterOf(response),
            ),
      );
      return null;
    }
    return response;
  }

  const body = (value: unknown) => ({
    method: "PATCH",
    body: JSON.stringify({ ...(value as object), reason: reason.trim() }),
  });

  async function moderate(action: "publish" | "hide") {
    if (await send(`/admin/forum-posts/${post.id}`, body({ action }))) onDone();
  }

  async function pin(next: boolean) {
    if (await send(`/admin/forum-threads/${post.id}`, body({ pinned: next })))
      onDone();
  }

  async function reveal() {
    const response = await send(`/admin/forum-posts/${post.id}/author`, {
      method: "POST",
      body: JSON.stringify({ reason: reason.trim() }),
    });
    if (response) {
      setIdentity(await response.json());
      setMessage(null);
    }
  }

  return (
    <li className="comment">
      <p className="comment__meta">
        <span className="chip">{STATUS[status]}</span>
        {pinned && <span className="chip">置頂</span>}
        <span className="comment__author">{authorName(post)}</span>
        <time dateTime={post.createdAt}>{postDate(post.createdAt)}</time>
        <span>{context}</span>
      </p>
      {post.title && <p className="forum-thread__title">{post.title}</p>}
      <p className="comment__body">{post.body}</p>
      {reports.length > 0 && (
        <div>
          <p className="comment__meta">{reports.length} 則未處理的檢舉</p>
          <ul className="moderation__reports">
            {reports.map((report, index) => (
              <li key={index}>
                {report.reason}（{postDate(report.createdAt)}）
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="comment-form">
        <label htmlFor={id}>處理原因（必填，記錄在稽核紀錄）</label>
        <textarea
          id={id}
          rows={2}
          maxLength={1000}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <div className="comment__actions">
          {(status !== "published" || reports.length > 0) && (
            <button
              className="btn btn--primary"
              type="button"
              disabled={busy}
              onClick={() => moderate("publish")}
            >
              {status === "published" ? "保留，結束檢舉" : "公開"}
            </button>
          )}
          {status !== "hidden" && (
            <button
              className="btn btn--secondary"
              type="button"
              disabled={busy}
              onClick={() => moderate("hide")}
            >
              隱藏
            </button>
          )}
          {pinned !== undefined && status === "published" && (
            <button
              className="btn btn--secondary"
              type="button"
              disabled={busy}
              onClick={() => pin(!pinned)}
            >
              {pinned ? "取消置頂" : "置頂"}
            </button>
          )}
          {post.anonymous && !identity && (
            <button
              className="btn btn--quiet"
              type="button"
              disabled={busy}
              onClick={reveal}
            >
              查看作者
            </button>
          )}
        </div>
      </div>
      <div aria-live="polite">
        {message && (
          <p className="note" role="alert">
            {message}
          </p>
        )}
        {identity && (
          <p className="callout">
            作者：{identity.displayName}（帳號 {identity.accountId}
            ）。這次查閱已連同原因記錄。
          </p>
        )}
      </div>
    </li>
  );
}
