"use client";

// The maintainer's moderation queue (D5 #71). The API decides who may moderate (app.accounts.is_admin); this page only
// hides itself from everyone else. Authors stay hidden unless the maintainer asks, gives a reason, and the lookup is
// recorded (ADR-0017).
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAccount, type Account } from "@/components/account";
import { apiFetch, authEnabled } from "@/lib/auth";
import {
  commentDate,
  errorMessage,
  paperPathFromId,
  retryAfterOf,
} from "@/lib/comments";
import type { components } from "@/lib/api.generated";

type Item = components["schemas"]["ModerationItem"];
type Identity = components["schemas"]["AuthorIdentity"];
type SignedIn = Extract<Account, { status: "signed-in" }>;

const STATUS = { pending: "等待審核", published: "公開中", hidden: "已隱藏" };

export function ModerationQueue() {
  const account = useAccount();
  if (!authEnabled) return <p>登入功能尚未開放。</p>;
  if (account.status === "loading") return <p aria-live="polite">載入中…</p>;
  if (account.status === "unavailable")
    return <p role="alert">目前無法連線到帳號服務，請稍後再試。</p>;
  if (account.status === "signed-out") {
    return (
      <p>
        請先<Link href="/login/?next=%2Fadmin%2Fcomments%2F">登入</Link>。
      </p>
    );
  }
  if (!account.isAdmin) return <p role="alert">需要管理者權限。</p>;
  return <Queue account={account} />;
}

function Queue({ account }: { account: SignedIn }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [version, setVersion] = useState(0);
  const token = account.token;

  useEffect(() => {
    let live = true;
    apiFetch("/admin/comments?limit=100", token)
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then(
        (page: { items: Item[] }) => live && setItems(page.items),
        () => live && setFailed(true),
      );
    return () => {
      live = false;
    };
    // Refetch on changes, not on hourly token refreshes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  if (failed) return <p role="alert">{errorMessage(null, "load")}</p>;
  if (items === null) return <p aria-live="polite">載入佇列中…</p>;
  if (items.length === 0) return <p>目前沒有等待處理的留言。</p>;
  return (
    <ul className="comment-list" aria-label="等待處理的留言">
      {items.map((item) => (
        <QueueItem
          key={item.comment.id}
          item={item}
          token={token}
          onDone={refresh}
        />
      ))}
    </ul>
  );
}

function QueueItem({
  item,
  token,
  onDone,
}: {
  item: Item;
  token: string;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const { comment } = item;

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
          ? "這則留言已經是這個狀態。"
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

  async function moderate(action: "publish" | "hide") {
    const response = await send(`/admin/comments/${comment.id}`, {
      method: "PATCH",
      body: JSON.stringify({ action, reason: reason.trim() }),
    });
    if (response) onDone();
  }

  async function reveal() {
    const response = await send(`/admin/comments/${comment.id}/author`, {
      method: "POST",
      body: JSON.stringify({ reason: reason.trim() }),
    });
    if (response) {
      setIdentity(await response.json());
      setMessage(null);
    }
  }

  const id = `reason-${comment.id}`;
  return (
    <li className="comment">
      <p className="comment__meta">
        <span className="chip">{STATUS[item.status]}</span>
        <span className="comment__author">
          {comment.anonymous ? "匿名讀者" : comment.displayName}
        </span>
        <time dateTime={comment.createdAt}>
          {commentDate(comment.createdAt)}
        </time>
        <Link href={paperPathFromId(comment.paperId)}>看文獻頁</Link>
      </p>
      <p className="comment__body">{comment.body}</p>
      {item.reportCount > 0 && (
        <div>
          <p className="comment__meta">{item.reportCount} 則未處理的檢舉</p>
          <ul className="moderation__reports">
            {item.reports.map((report, index) => (
              <li key={index}>
                {report.reason}（{commentDate(report.createdAt)}）
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
          <button
            className="btn btn--primary"
            type="button"
            disabled={busy}
            onClick={() => moderate("publish")}
          >
            {item.status === "published" ? "保留，結束檢舉" : "公開"}
          </button>
          <button
            className="btn btn--secondary"
            type="button"
            disabled={busy}
            onClick={() => moderate("hide")}
          >
            隱藏
          </button>
          {comment.anonymous && !identity && (
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
