"use client";

// Reader discussion on a paper page (D3 #69). Everything here runs in the browser: the page HTML stays the same for
// every reader (ADR-0020). Which comments are the reader's own comes from the private /me/comments, never from the
// public list, which has no author field (ADR-0017).
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAccount, type Account } from "@/components/account";
import { apiFetch, apiUrl, authEnabled, returnPath } from "@/lib/auth";
import {
  BODY_MAX,
  bodyError,
  commentDate,
  errorMessage,
  ownComments,
  type Action,
  type CommentPage,
  type CommentReceipt,
  type LikeState,
  type OwnedComment,
  type OwnedCommentPage,
  type PublicComment,
} from "@/lib/comments";

type SignedIn = Extract<Account, { status: "signed-in" }>;
type List =
  | { kind: "loading" | "error" }
  | { kind: "ready"; items: PublicComment[]; next: string | null };

/** Shown only when the build knows the API and sign-in service. */
export function ReaderComments({ paperId }: { paperId: string }) {
  return authEnabled ? <Discussion paperId={paperId} /> : null;
}

function Discussion({ paperId }: { paperId: string }) {
  const account = useAccount();
  const signedIn = account.status === "signed-in" ? account : null;
  const [list, setList] = useState<List>({ kind: "loading" });
  const [owned, setOwned] = useState<{ user: string; items: OwnedComment[] }>({
    user: "",
    items: [],
  });
  const [likes, setLikes] = useState<{ user: string; ids: Set<string> }>({
    user: "",
    ids: new Set(),
  });
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  const loadPage = useCallback(
    async (cursor: string | null): Promise<CommentPage> => {
      const query = new URLSearchParams({ limit: "50" });
      if (cursor) query.set("cursor", cursor);
      const response = await fetch(
        apiUrl(`/papers/${encodeURIComponent(paperId)}/comments?${query}`),
        { credentials: "omit", cache: "no-store" },
      );
      if (!response.ok) throw new Error(`comments ${response.status}`);
      return response.json();
    },
    [paperId],
  );

  useEffect(() => {
    let live = true;
    loadPage(null).then(
      (page) =>
        live &&
        setList({ kind: "ready", items: page.items, next: page.nextCursor }),
      () => live && setList({ kind: "error" }),
    );
    return () => {
      live = false;
    };
  }, [loadPage, version]);

  const user = signedIn?.userId ?? "";
  const token = signedIn?.token ?? "";
  useEffect(() => {
    if (!user) return;
    let live = true;
    // The reader's own comments across papers; 100 covers far more than anyone writes before pagination matters.
    apiFetch("/me/comments?limit=100", token)
      .then((response) => (response.ok ? response.json() : null))
      .then((page: OwnedCommentPage | null) => {
        if (live && page) setOwned({ user, items: page.items });
      })
      .catch(() => undefined);
    apiFetch(`/me/likes?paperId=${encodeURIComponent(paperId)}`, token)
      .then((response) => (response.ok ? response.json() : null))
      .then((own: { commentIds: string[] } | null) => {
        if (live && own) setLikes({ user, ids: new Set(own.commentIds) });
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
    // The token refreshes hourly; refetching then is unnecessary, so only the user and changes count.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, version, paperId]);

  const mine = ownComments(owned.user === user ? owned.items : [], paperId);
  const liked = likes.user === user ? likes.ids : new Set<string>();
  // Until both private lists arrive, an own comment looks like someone else's; offer no like button before that.
  const ownKnown = Boolean(user) && owned.user === user && likes.user === user;

  async function more() {
    if (list.kind !== "ready" || !list.next) return;
    try {
      const page = await loadPage(list.next);
      setList({
        kind: "ready",
        items: [...list.items, ...page.items],
        next: page.nextCursor,
      });
    } catch {
      setList({ kind: "error" });
    }
  }

  return (
    <section className="page__section comments" aria-labelledby="discussion">
      <h2 id="discussion">讀者討論</h2>
      <p className="note">
        讀者留言是個人意見，不是本站的文獻整理，也沒有經過醫學審核。
      </p>
      {signedIn && mine.unpublished.length > 0 && (
        <ul className="comment-list" aria-label="只有你看得到的留言">
          {mine.unpublished.map((item) => (
            <CommentItem
              key={item.comment.id}
              comment={item.comment}
              status={item.status}
              mine
              account={signedIn}
              onChanged={refresh}
            />
          ))}
        </ul>
      )}
      {list.kind === "loading" && <p aria-live="polite">載入留言中…</p>}
      {list.kind === "error" && (
        <p role="alert">
          {errorMessage(null, "load")}{" "}
          <button
            className="btn btn--secondary"
            type="button"
            onClick={() => {
              setList({ kind: "loading" });
              refresh();
            }}
          >
            重新載入
          </button>
        </p>
      )}
      {list.kind === "ready" && list.items.length === 0 && <p>還沒有留言。</p>}
      {list.kind === "ready" && list.items.length > 0 && (
        <ul className="comment-list" aria-label="讀者留言">
          {list.items.map((comment) => (
            <CommentItem
              key={comment.id}
              comment={comment}
              status="published"
              mine={mine.ids.has(comment.id)}
              liked={liked.has(comment.id)}
              ownKnown={ownKnown}
              account={signedIn}
              onChanged={refresh}
            />
          ))}
        </ul>
      )}
      {list.kind === "ready" && list.next && (
        <button className="btn btn--secondary" type="button" onClick={more}>
          載入更多留言
        </button>
      )}
      <CommentForm paperId={paperId} account={account} onPosted={refresh} />
    </section>
  );
}

function CommentForm({
  paperId,
  account,
  onPosted,
}: {
  paperId: string;
  account: Account;
  onPosted: () => void;
}) {
  const path = usePathname();
  const [body, setBody] = useState("");
  const [anonymous, setAnonymous] = useState(false);
  const [state, setState] = useState<
    | { kind: "idle" | "sending" }
    | { kind: "error"; message: string }
    | { kind: "sent"; status: CommentReceipt["status"] }
  >({ kind: "idle" });
  // Blocks a second submit (double click, Enter twice) before React re-renders the disabled button.
  const sending = useRef(false);

  if (account.status === "loading") return null;
  if (account.status === "unavailable") {
    return <p role="alert">目前無法連線到帳號服務，暫時不能留言。</p>;
  }
  if (account.status === "signed-out") {
    return (
      <p className="comment-gate">
        登入後就能留言，可以選擇署名或匿名。{" "}
        <Link href={`/login/?next=${encodeURIComponent(returnPath(path))}`}>
          登入
        </Link>
      </p>
    );
  }
  if (account.displayName === null) {
    return (
      <p className="comment-gate">
        留言前請先
        <Link
          href={`/account/?welcome=1&next=${encodeURIComponent(returnPath(path))}`}
        >
          設定顯示名稱
        </Link>
        。
      </p>
    );
  }
  const token = account.token;
  const name = account.displayName;
  const count = [...body].length;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (sending.current) return;
    const problem = bodyError(body);
    if (problem) return setState({ kind: "error", message: problem });
    sending.current = true;
    setState({ kind: "sending" });
    const response = await apiFetch(
      `/papers/${encodeURIComponent(paperId)}/comments`,
      token,
      { method: "POST", body: JSON.stringify({ body, anonymous }) },
    ).catch(() => null);
    sending.current = false;
    if (!response?.ok) {
      const retryAfter = Number(response?.headers.get("Retry-After")) || null;
      return setState({
        kind: "error",
        message: errorMessage(response?.status ?? null, "post", retryAfter),
      });
    }
    const receipt: CommentReceipt = await response.json();
    setBody("");
    setState({ kind: "sent", status: receipt.status });
    onPosted();
  }

  const error = state.kind === "error" ? state.message : null;
  return (
    <form className="comment-form" onSubmit={submit} noValidate>
      <h3>留言</h3>
      <label htmlFor="comment-body">你的留言</label>
      <textarea
        id="comment-body"
        name="body"
        rows={4}
        value={body}
        aria-invalid={error !== null && bodyError(body) !== null}
        aria-describedby="comment-help"
        onChange={(event) => {
          setBody(event.target.value);
          if (state.kind !== "sending") setState({ kind: "idle" });
        }}
      />
      <p id="comment-help" className="note">
        {count} / {BODY_MAX} 字。純文字，不支援粗體或連結格式。
      </p>
      <fieldset className="comment-form__identity">
        <legend>顯示方式</legend>
        <label>
          <input
            type="radio"
            name="identity"
            checked={!anonymous}
            onChange={() => setAnonymous(false)}
          />
          署名，顯示為「{name}」
        </label>
        <label>
          <input
            type="radio"
            name="identity"
            checked={anonymous}
            onChange={() => setAnonymous(true)}
          />
          匿名：其他讀者看不到你的名稱；你本人和維護者仍能對應到你的帳號
        </label>
      </fieldset>
      <button
        className="btn btn--primary"
        type="submit"
        disabled={state.kind === "sending"}
      >
        {state.kind === "sending" ? "送出中…" : "送出留言"}
      </button>
      <div aria-live="polite">
        {error && (
          <p className="callout" role="alert">
            {error}
          </p>
        )}
        {state.kind === "sent" && (
          <p className="callout">
            {state.status === "pending"
              ? "已送出。第一則留言要等維護者審核後才會公開，在那之前只有你看得到。"
              : "已發布。"}
          </p>
        )}
      </div>
    </form>
  );
}

function CommentItem({
  comment,
  status,
  mine,
  account,
  onChanged,
  liked = false,
  ownKnown = false,
}: {
  comment: PublicComment;
  status: OwnedComment["status"];
  mine: boolean;
  account: SignedIn | null;
  onChanged: () => void;
  liked?: boolean;
  ownKnown?: boolean;
}) {
  const [mode, setMode] = useState<"view" | "edit" | "delete" | "report">(
    "view",
  );
  const [draft, setDraft] = useState(comment.body);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{
    text: string;
    error: boolean;
  } | null>(null);

  async function send(
    action: Action,
    path: string,
    init: RequestInit,
  ): Promise<boolean> {
    if (!account || busy) return false;
    setBusy(true);
    const response = await apiFetch(path, account.token, init).catch(
      () => null,
    );
    setBusy(false);
    if (response?.ok) return true;
    setMessage({
      text: errorMessage(response?.status ?? null, action),
      error: true,
    });
    return false;
  }

  async function saveEdit(event: React.FormEvent) {
    event.preventDefault();
    const problem = bodyError(draft);
    if (problem) return setMessage({ text: problem, error: true });
    const ok = await send("edit", `/comments/${comment.id}`, {
      method: "PATCH",
      body: JSON.stringify({ body: draft }),
    });
    if (ok) {
      setMode("view");
      setMessage(null);
      onChanged();
    }
  }

  async function remove() {
    if (await send("delete", `/comments/${comment.id}`, { method: "DELETE" }))
      onChanged();
  }

  async function report(event: React.FormEvent) {
    event.preventDefault();
    if (!reason.trim())
      return setMessage({ text: "請寫下檢舉原因", error: true });
    const ok = await send("report", `/comments/${comment.id}/reports`, {
      method: "POST",
      body: JSON.stringify({ reason: reason.trim() }),
    });
    if (ok) {
      setMode("view");
      setReason("");
      setMessage({ text: "已收到檢舉，維護者會處理。", error: false });
    }
  }

  const edited = comment.updatedAt !== comment.createdAt;
  const canReport =
    !mine && status === "published" && account?.displayName != null;
  return (
    <li className="comment">
      <p className="comment__meta">
        <span className="comment__author">
          {comment.anonymous ? "匿名讀者" : comment.displayName}
        </span>
        {mine && <span className="chip">你的留言</span>}
        <time dateTime={comment.createdAt}>
          {commentDate(comment.createdAt)}
        </time>
        {edited && <span>（已編輯）</span>}
        {status === "pending" && (
          <span className="chip">等待審核，只有你看得到</span>
        )}
        {status === "hidden" && (
          <span className="chip">已被維護者隱藏，只有你看得到</span>
        )}
      </p>
      {mode === "edit" ? (
        <form className="comment-form" onSubmit={saveEdit} noValidate>
          <label htmlFor={`edit-${comment.id}`}>修改留言</label>
          <textarea
            id={`edit-${comment.id}`}
            rows={4}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="comment__actions">
            <button className="btn btn--primary" type="submit" disabled={busy}>
              儲存
            </button>
            <button
              className="btn btn--quiet"
              type="button"
              onClick={() => {
                setMode("view");
                setDraft(comment.body);
                setMessage(null);
              }}
            >
              取消
            </button>
          </div>
        </form>
      ) : (
        <p className="comment__body">{comment.body}</p>
      )}
      {status === "published" && (
        <LikeButton
          // Remount when the server's numbers change, so a refresh replaces any optimistic state.
          key={`${comment.likeCount}-${liked}`}
          commentId={comment.id}
          count={comment.likeCount}
          liked={liked}
          // Readers with a display name can like others' comments; everyone else just sees the count.
          canLike={ownKnown && !mine && account?.displayName != null}
          token={account?.token ?? ""}
        />
      )}
      {mode === "view" && (mine || canReport) && (
        <div className="comment__actions">
          {mine ? (
            <>
              <button
                className="btn btn--quiet"
                type="button"
                onClick={() => setMode("edit")}
              >
                修改
              </button>
              <button
                className="btn btn--quiet"
                type="button"
                onClick={() => setMode("delete")}
              >
                刪除
              </button>
            </>
          ) : (
            <button
              className="btn btn--quiet"
              type="button"
              onClick={() => {
                setMode("report");
                setMessage(null);
              }}
            >
              檢舉
            </button>
          )}
        </div>
      )}
      {mode === "delete" && (
        <div className="comment__actions" role="group" aria-label="確認刪除">
          <p>確定刪除這則留言？刪除後無法復原。</p>
          <button
            className="btn btn--secondary"
            type="button"
            disabled={busy}
            onClick={remove}
          >
            確定刪除
          </button>
          <button
            className="btn btn--quiet"
            type="button"
            onClick={() => setMode("view")}
          >
            取消
          </button>
        </div>
      )}
      {mode === "report" && (
        <form className="comment-form" onSubmit={report} noValidate>
          <label htmlFor={`report-${comment.id}`}>檢舉原因</label>
          <textarea
            id={`report-${comment.id}`}
            rows={2}
            maxLength={1000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="comment__actions">
            <button className="btn btn--primary" type="submit" disabled={busy}>
              送出檢舉
            </button>
            <button
              className="btn btn--quiet"
              type="button"
              onClick={() => setMode("view")}
            >
              取消
            </button>
          </div>
        </form>
      )}
      <div aria-live="polite">
        {message && (
          <p className="note" role={message.error ? "alert" : undefined}>
            {message.text}
          </p>
        )}
      </div>
    </li>
  );
}

function LikeButton({
  commentId,
  count,
  liked,
  canLike,
  token,
}: {
  commentId: string;
  count: number;
  liked: boolean;
  canLike: boolean;
  token: string;
}) {
  const [state, setState] = useState<LikeState>({ likeCount: count, liked });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canLike) {
    return state.likeCount > 0 ? (
      <p className="comment__likes">{state.likeCount} 個讚</p>
    ) : null;
  }

  async function toggle() {
    if (busy) return;
    const before = state;
    const next = !before.liked;
    // Show the change at once; the server's answer (or a failure) settles it.
    setState({ liked: next, likeCount: before.likeCount + (next ? 1 : -1) });
    setBusy(true);
    setError(null);
    const response = await apiFetch(`/comments/${commentId}/likes`, token, {
      method: next ? "PUT" : "DELETE",
    }).catch(() => null);
    setBusy(false);
    if (response?.ok) return setState(await response.json());
    setState(before);
    setError(errorMessage(response?.status ?? null, "like"));
  }

  return (
    <div className="comment__likes">
      <button
        className="btn btn--quiet"
        type="button"
        aria-pressed={state.liked}
        onClick={toggle}
      >
        讚<span aria-hidden="true">・{state.likeCount}</span>
        <span className="visually-hidden">，目前 {state.likeCount} 個讚</span>
      </button>
      {error && (
        <p className="note" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
