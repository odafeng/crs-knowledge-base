"use client";

// The colorectal surgeon forum (H7 #129, ADR-0022). Everything here runs in the browser, so the page HTML is the same
// for everyone and holds no forum content (ADR-0020); the API answers forum requests only for verified members and
// gives everyone else 404. Which posts are the member's own comes from the API's `mine`, never from names.
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAccount, type Account } from "@/components/account";
import { AiChip } from "@/components/reading";
import { paperPathFromId, retryAfterOf } from "@/lib/comments";
import { apiFetch, authEnabled, returnPath } from "@/lib/auth";
import {
  BODY_MAX,
  DEIDENTIFY,
  authorName,
  bodyError,
  errorMessage,
  paperIdParam,
  postDate,
  receiptMessage,
  threadPath,
  titleError,
  type Action,
  type OpeningPost,
  type OwnPost,
  type PostReceipt,
  type Reply,
  type ThreadDetail,
  type ThreadPage,
  type ThreadSummary,
} from "@/lib/forum";
import { loadMembership, type Membership } from "@/lib/surgeons";

type SignedIn = Extract<Account, { status: "signed-in" }>;
export type TopicLabel = { key: string; label: string };

// --- who may enter -----------------------------------------------------------------------------------------------

const ABOUT =
  "論壇只開放給通過驗證的大腸直腸外科會員：大腸直腸外科專科醫師，以及受訓中的住院醫師與 fellow。論壇內容不公開，搜尋引擎也不收錄。";

/** Renders its children only for verified members; everyone else gets the explanation and the next step. */
function MembersOnly({
  children,
}: {
  children: (account: SignedIn) => React.ReactNode;
}) {
  const account = useAccount();
  const path = usePathname();
  const [membership, setMembership] = useState<{
    user: string;
    value: Membership | null;
  } | null>(null);
  const signedIn = account.status === "signed-in" ? account : null;
  const user = signedIn?.userId ?? "";
  const named = Boolean(signedIn?.displayName);

  useEffect(() => {
    if (!signedIn || !named) return;
    let live = true;
    loadMembership(signedIn.token).then(
      (value) => live && setMembership({ user, value }),
    );
    return () => {
      live = false;
    };
    // Once per account; hourly token refreshes do not change membership.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, named]);

  if (!authEnabled) return <p>{ABOUT}</p>;
  if (account.status === "loading") return <p aria-live="polite">載入中…</p>;
  if (account.status === "unavailable")
    return <p role="alert">目前無法連線到帳號服務，請稍後再試。</p>;
  if (account.status === "signed-out") {
    return (
      <div className="forum-gate">
        <p className="forum-gate__kicker">醫師會員限定</p>
        <p>{ABOUT}</p>
        <p>
          <Link
            className="btn btn--primary"
            href={`/login/?next=${encodeURIComponent(returnPath(path))}`}
          >
            登入
          </Link>
        </p>
      </div>
    );
  }
  if (!account.displayName) {
    return (
      <div className="forum-gate">
        <p className="forum-gate__kicker">醫師會員限定</p>
        <p>{ABOUT}</p>
        <p>
          請先
          <Link href="/account/?welcome=1&next=%2Faccount%2F">
            設定顯示名稱
          </Link>
          ，再申請驗證。
        </p>
      </div>
    );
  }
  if (membership?.user !== user) return <p aria-live="polite">載入中…</p>;
  if (membership.value === null)
    return <p role="alert">暫時無法確認會員資格，請稍後再試。</p>;
  if (membership.value.status !== "verified") {
    return (
      <div className="forum-gate">
        <p className="forum-gate__kicker">醫師會員限定</p>
        <p>{ABOUT}</p>
        <p>
          {membership.value.status === "pending"
            ? "你的驗證申請正在審核中，開通後就能進入論壇。"
            : "你還不是大腸直腸外科會員。"}{" "}
          <Link href="/account/">到帳號設定查看或申請</Link>
        </p>
      </div>
    );
  }
  return children(account);
}

// --- the thread list ---------------------------------------------------------------------------------------------

type List =
  | { kind: "loading" | "error" }
  | {
      kind: "ready";
      pinned: ThreadSummary[];
      items: ThreadSummary[];
      next: string | null;
    };

export function ForumHome({ topics }: { topics: TopicLabel[] }) {
  return (
    <MembersOnly>
      {(account) => <Threads account={account} topics={topics} />}
    </MembersOnly>
  );
}

function Threads({
  account,
  topics,
}: {
  account: SignedIn;
  topics: TopicLabel[];
}) {
  const [list, setList] = useState<List>({ kind: "loading" });
  const [own, setOwn] = useState<OwnPost[]>([]);
  const [version, setVersion] = useState(0);
  const token = account.token;

  const loadPage = useCallback(
    async (cursor: string | null): Promise<ThreadPage> => {
      const query = new URLSearchParams({ limit: "20" });
      if (cursor) query.set("cursor", cursor);
      const response = await apiFetch(`/forum/threads?${query}`, token);
      if (!response.ok) throw new Error(`threads ${response.status}`);
      return response.json();
    },
    // Hourly token refreshes do not change the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [account.userId],
  );

  useEffect(() => {
    let live = true;
    loadPage(null).then(
      (page) =>
        live &&
        setList({
          kind: "ready",
          pinned: page.pinned,
          items: page.items,
          next: page.nextCursor,
        }),
      () => live && setList({ kind: "error" }),
    );
    apiFetch("/forum/me/posts?limit=100", token)
      .then((response) => (response.ok ? response.json() : null))
      .then(
        (page: { items: OwnPost[] } | null) =>
          live && page && setOwn(page.items.filter((i) => !i.post.threadId)),
      )
      .catch(() => undefined);
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadPage, version]);

  async function more() {
    if (list.kind !== "ready" || !list.next) return;
    try {
      const page = await loadPage(list.next);
      setList({
        ...list,
        items: [...list.items, ...page.items],
        next: page.nextCursor,
      });
    } catch {
      setList({ kind: "error" });
    }
  }

  const labels = new Map(topics.map((t) => [t.key, t.label]));
  return (
    <div className="forum-layout">
      <aside className="forum-layout__rail" aria-label="發文">
        <Link className="btn btn--primary forum-layout__cta" href="/forum/new/">
          開新話題
        </Link>
        <ForumRules />
        {own.length > 0 && (
          <section aria-labelledby="forum-own">
            <h2 id="forum-own">只有你看得到的話題</h2>
            <ul className="comment-list">
              {own.map((item) => (
                <li className="comment" key={item.post.id}>
                  <p className="comment__meta">
                    <span className="chip">
                      {item.status === "pending"
                        ? "等待審核"
                        : "已被維護者隱藏"}
                    </span>
                    <time dateTime={item.post.createdAt}>
                      {postDate(item.post.createdAt)}
                    </time>
                  </p>
                  <p className="forum-thread__title">{item.post.title}</p>
                  <p className="comment__body">{item.post.body}</p>
                  <DeleteButton
                    postId={item.post.id}
                    token={token}
                    onDeleted={() => setVersion((v) => v + 1)}
                  />
                </li>
              ))}
            </ul>
          </section>
        )}
      </aside>
      <div className="forum-layout__main">
        {list.kind === "loading" && <p aria-live="polite">載入話題中…</p>}
        {list.kind === "error" && (
          <p role="alert">
            {errorMessage(null, "load")}{" "}
            <button
              className="btn btn--secondary"
              type="button"
              onClick={() => {
                setList({ kind: "loading" });
                setVersion((v) => v + 1);
              }}
            >
              重新載入
            </button>
          </p>
        )}
        {list.kind === "ready" && (
          <>
            {list.pinned.length > 0 && (
              <ul className="forum-rows" aria-label="置頂話題">
                {list.pinned.map((thread) => (
                  <ThreadRow key={thread.id} thread={thread} labels={labels} />
                ))}
              </ul>
            )}
            {list.items.length === 0 && list.pinned.length === 0 ? (
              <p>還沒有話題，來開第一個吧。</p>
            ) : (
              <ul className="forum-rows" aria-label="話題">
                {list.items.map((thread) => (
                  <ThreadRow key={thread.id} thread={thread} labels={labels} />
                ))}
              </ul>
            )}
            {list.next && (
              <button
                className="btn btn--secondary"
                type="button"
                onClick={more}
              >
                載入更多話題
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** What may not be posted, beside the list and the thread (ADR-0022). */
function ForumRules() {
  return (
    <section className="forum-rules" aria-labelledby="forum-rules">
      <h2 id="forum-rules">發文須知</h2>
      <p>{DEIDENTIFY}</p>
      <p>貼文是個人意見，不是本站的文獻整理。</p>
    </section>
  );
}

function ThreadRow({
  thread,
  labels,
}: {
  thread: ThreadSummary;
  labels: Map<string, string>;
}) {
  const topic = thread.topicKey ? labels.get(thread.topicKey) : undefined;
  return (
    <li className="forum-row">
      <div className="forum-row__main">
        <Link className="forum-thread__title" href={threadPath(thread.id)}>
          {thread.title}
        </Link>
        <p className="comment__meta">
          {thread.pinned && <span className="chip">置頂</span>}
          {topic && <span className="chip">{topic}</span>}
          <span className="comment__author">{authorName(thread)}</span>
          {thread.ai && <AiChip label="AI" />}
          <time dateTime={thread.createdAt}>{postDate(thread.createdAt)}</time>
          {thread.likeCount > 0 && <span>{thread.likeCount} 個讚</span>}
        </p>
      </div>
      <p className="forum-row__stat">
        <span className="forum-row__count">{thread.replyCount}</span> 則回覆
      </p>
      <p className="forum-row__stat">
        {thread.lastReplyAt ? (
          <>
            最新回覆{" "}
            <time dateTime={thread.lastReplyAt}>
              {postDate(thread.lastReplyAt)}
            </time>
          </>
        ) : (
          "還沒有回覆"
        )}
      </p>
    </li>
  );
}

function DeleteButton({
  postId,
  token,
  onDeleted,
}: {
  postId: string;
  token: string;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function remove() {
    const response = await apiFetch(`/forum/posts/${postId}`, token, {
      method: "DELETE",
    }).catch(() => null);
    if (response?.ok) return onDeleted();
    setError(errorMessage(response?.status ?? null, "delete"));
  }
  return (
    <div className="comment__actions">
      {confirming ? (
        <>
          <p>確定刪除？刪除後無法復原。</p>
          <button className="btn btn--secondary" type="button" onClick={remove}>
            確定刪除
          </button>
          <button
            className="btn btn--quiet"
            type="button"
            onClick={() => setConfirming(false)}
          >
            取消
          </button>
        </>
      ) : (
        <button
          className="btn btn--quiet"
          type="button"
          onClick={() => setConfirming(true)}
        >
          刪除
        </button>
      )}
      {error && (
        <p className="note" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

// --- writing -----------------------------------------------------------------------------------------------------

/** The identity choice and the de-identification check every post goes through (ADR-0022). */
function PostFields({
  idPrefix,
  name,
  anonymous,
  setAnonymous,
  confirmed,
  setConfirmed,
}: {
  idPrefix: string;
  name: string;
  anonymous: boolean;
  setAnonymous: (value: boolean) => void;
  confirmed: boolean;
  setConfirmed: (value: boolean) => void;
}) {
  return (
    <>
      <fieldset className="comment-form__identity">
        <legend>顯示方式</legend>
        <label>
          <input
            type="radio"
            name={`${idPrefix}-identity`}
            checked={!anonymous}
            onChange={() => setAnonymous(false)}
          />
          署名，顯示為「{name}」
        </label>
        <label>
          <input
            type="radio"
            name={`${idPrefix}-identity`}
            checked={anonymous}
            onChange={() => setAnonymous(true)}
          />
          匿名：其他會員看不到你的名稱；你本人和維護者仍能對應到你的帳號
        </label>
      </fieldset>
      <div className="callout forum-deidentify" id={`${idPrefix}-deidentify`}>
        <p>{DEIDENTIFY}</p>
        <label>
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          我確認內容不含可識別病人的資訊
        </label>
      </div>
    </>
  );
}

function writeProblem(
  body: string,
  confirmed: boolean,
  title?: string,
): string | null {
  return (
    (title !== undefined ? titleError(title) : null) ??
    bodyError(body) ??
    (confirmed ? null : "送出前請確認內容不含可識別病人的資訊。")
  );
}

export function NewThread({ topics }: { topics: TopicLabel[] }) {
  return (
    <MembersOnly>
      {(account) => <NewThreadForm account={account} topics={topics} />}
    </MembersOnly>
  );
}

function NewThreadForm({
  account,
  topics,
}: {
  account: SignedIn;
  topics: TopicLabel[];
}) {
  const router = useRouter();
  const paperId = paperIdParam(useSearchParams().get("paperId"));
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [topic, setTopic] = useState("");
  const [anonymous, setAnonymous] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [state, setState] = useState<
    | { kind: "idle" | "sending" }
    | { kind: "error"; message: string }
    | { kind: "pending" }
  >({ kind: "idle" });
  const sending = useRef(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (sending.current) return;
    const problem = writeProblem(body, confirmed, title);
    if (problem) return setState({ kind: "error", message: problem });
    sending.current = true;
    setState({ kind: "sending" });
    const response = await apiFetch("/forum/threads", account.token, {
      method: "POST",
      body: JSON.stringify({
        title: title.trim(),
        body,
        anonymous,
        topicKey: topic || null,
        paperId,
      }),
    }).catch(() => null);
    sending.current = false;
    if (!response?.ok) {
      return setState({
        kind: "error",
        message: errorMessage(
          response?.status ?? null,
          "post",
          retryAfterOf(response),
        ),
      });
    }
    const receipt: PostReceipt = await response.json();
    if (receipt.status === "published")
      return router.push(threadPath(receipt.threadId));
    setState({ kind: "pending" });
  }

  if (state.kind === "pending") {
    return (
      <div aria-live="polite">
        <p className="callout">{receiptMessage("pending")}</p>
        <Link className="btn btn--secondary" href="/forum/">
          回論壇
        </Link>
      </div>
    );
  }
  const error = state.kind === "error" ? state.message : null;
  return (
    <form className="comment-form" onSubmit={submit} noValidate>
      {paperId && (
        <p className="note">
          這個話題會連結到文獻：
          <Link href={paperPathFromId(paperId)}>{paperId}</Link>
        </p>
      )}
      <label htmlFor="thread-title">標題</label>
      <input
        id="thread-title"
        className="forum-input"
        value={title}
        aria-invalid={error !== null && titleError(title) !== null}
        onChange={(event) => setTitle(event.target.value)}
      />
      <label htmlFor="thread-topic">相關主題（可不選）</label>
      <select
        id="thread-topic"
        className="forum-input"
        value={topic}
        onChange={(event) => setTopic(event.target.value)}
      >
        <option value="">不指定</option>
        {topics.map((t) => (
          <option key={t.key} value={t.key}>
            {t.label}
          </option>
        ))}
      </select>
      <label htmlFor="thread-body">內容</label>
      <textarea
        id="thread-body"
        rows={8}
        value={body}
        aria-invalid={error !== null && bodyError(body) !== null}
        aria-describedby="thread-help"
        onChange={(event) => setBody(event.target.value)}
      />
      <p id="thread-help" className="note">
        {[...body].length} / {BODY_MAX} 字。純文字，不支援粗體或連結格式。
      </p>
      <PostFields
        idPrefix="thread"
        name={account.displayName ?? ""}
        anonymous={anonymous}
        setAnonymous={setAnonymous}
        confirmed={confirmed}
        setConfirmed={setConfirmed}
      />
      <button
        className="btn btn--primary"
        type="submit"
        disabled={state.kind === "sending"}
      >
        {state.kind === "sending" ? "送出中…" : "發表話題"}
      </button>
      <div aria-live="polite">
        {error && (
          <p className="callout" role="alert">
            {error}
          </p>
        )}
      </div>
    </form>
  );
}

// --- a thread ----------------------------------------------------------------------------------------------------

type Detail =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "error" }
  | {
      kind: "ready";
      thread: OpeningPost;
      replies: Reply[];
      next: string | null;
    };

export function ForumThread({
  id,
  topics,
}: {
  id: string;
  topics: TopicLabel[];
}) {
  return (
    <MembersOnly>
      {(account) => <Thread id={id} account={account} topics={topics} />}
    </MembersOnly>
  );
}

function Thread({
  id,
  account,
  topics,
}: {
  id: string;
  account: SignedIn;
  topics: TopicLabel[];
}) {
  const router = useRouter();
  const [detail, setDetail] = useState<Detail>({ kind: "loading" });
  const [own, setOwn] = useState<OwnPost[]>([]);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  const token = account.token;

  const loadPage = useCallback(
    async (cursor: string | null): Promise<ThreadDetail | null> => {
      const query = new URLSearchParams({ limit: "50" });
      if (cursor) query.set("cursor", cursor);
      const response = await apiFetch(
        `/forum/threads/${encodeURIComponent(id)}?${query}`,
        token,
      );
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`thread ${response.status}`);
      return response.json();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [id, account.userId],
  );

  useEffect(() => {
    let live = true;
    loadPage(null).then(
      (page) => {
        if (!live) return;
        setDetail(
          page
            ? {
                kind: "ready",
                thread: page.thread,
                replies: page.replies,
                next: page.nextCursor,
              }
            : { kind: "missing" },
        );
      },
      () => live && setDetail({ kind: "error" }),
    );
    apiFetch("/forum/me/posts?limit=100", token)
      .then((response) => (response.ok ? response.json() : null))
      .then(
        (page: { items: OwnPost[] } | null) =>
          live &&
          page &&
          setOwn(page.items.filter((i) => i.post.threadId === id)),
      )
      .catch(() => undefined);
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadPage, version]);

  async function more() {
    if (detail.kind !== "ready" || !detail.next) return;
    try {
      const page = await loadPage(detail.next);
      if (!page) return setDetail({ kind: "missing" });
      setDetail({
        ...detail,
        replies: [...detail.replies, ...page.replies],
        next: page.nextCursor,
      });
    } catch {
      setDetail({ kind: "error" });
    }
  }

  if (detail.kind === "loading") return <p aria-live="polite">載入話題中…</p>;
  if (detail.kind === "error")
    return <p role="alert">{errorMessage(null, "load")}</p>;
  if (detail.kind === "missing") {
    return (
      <>
        <h1>找不到這個話題</h1>
        <p>話題可能已被作者刪除或由維護者隱藏。</p>
        <Link className="btn btn--secondary" href="/forum/">
          回論壇
        </Link>
      </>
    );
  }
  const { thread } = detail;
  const topic = topics.find((t) => t.key === thread.topicKey)?.label;
  return (
    <>
      <header className="page-head">
        <p className="comment__meta">
          <Link href="/forum/">論壇</Link>
          {thread.pinned && <span className="chip">置頂</span>}
          {topic && <span className="chip">{topic}</span>}
          {thread.paperId && (
            <Link href={paperPathFromId(thread.paperId)}>相關文獻</Link>
          )}
        </p>
        <h1>{thread.title}</h1>
      </header>
      <div className="split">
        <div>
          <ul className="comment-list" aria-label="話題內容">
            <PostItem
              post={thread}
              title={thread.title}
              account={account}
              onChanged={refresh}
              onDeleted={() => router.push("/forum/")}
            />
          </ul>
          <section aria-labelledby="forum-replies">
            <h2 id="forum-replies">回覆</h2>
            {detail.replies.length > 0 && (
              <ul className="comment-list" aria-label="回覆">
                {detail.replies.map((reply) => (
                  <PostItem
                    key={reply.id}
                    post={reply}
                    account={account}
                    onChanged={refresh}
                    onDeleted={refresh}
                  />
                ))}
              </ul>
            )}
            {detail.next && (
              <button
                className="btn btn--secondary"
                type="button"
                onClick={more}
              >
                載入更多回覆
              </button>
            )}
            {own.length > 0 && (
              <ul className="comment-list" aria-label="只有你看得到的回覆">
                {own.map((item) => (
                  <li className="comment" key={item.post.id}>
                    <p className="comment__meta">
                      <span className="comment__author">
                        {authorName(item.post)}
                      </span>
                      <span className="chip">
                        {item.status === "pending"
                          ? "等待審核，只有你看得到"
                          : "已被維護者隱藏，只有你看得到"}
                      </span>
                    </p>
                    <p className="comment__body">{item.post.body}</p>
                    <DeleteButton
                      postId={item.post.id}
                      token={token}
                      onDeleted={refresh}
                    />
                  </li>
                ))}
              </ul>
            )}
            <ReplyForm
              threadId={thread.id}
              account={account}
              onPosted={refresh}
            />
          </section>
        </div>
        <aside className="split__rail" aria-label="話題資訊">
          <dl className="facts">
            {topic && (
              <>
                <dt>主題</dt>
                <dd>{topic}</dd>
              </>
            )}
            <dt>開始於</dt>
            <dd>
              <time dateTime={thread.createdAt}>
                {postDate(thread.createdAt)}
              </time>
            </dd>
            <dt>回覆</dt>
            <dd>{detail.replies.length + (detail.next ? "+" : "")} 則</dd>
          </dl>
          <div className="actions actions--rail">
            <a className="btn btn--primary" href="#forum-replies">
              回覆這個話題
            </a>
            {thread.paperId && (
              <Link
                className="btn btn--secondary"
                href={paperPathFromId(thread.paperId)}
              >
                看相關文獻
              </Link>
            )}
          </div>
          <ForumRules />
        </aside>
      </div>
    </>
  );
}

function ReplyForm({
  threadId,
  account,
  onPosted,
}: {
  threadId: string;
  account: SignedIn;
  onPosted: () => void;
}) {
  const [body, setBody] = useState("");
  const [anonymous, setAnonymous] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [state, setState] = useState<
    | { kind: "idle" | "sending" }
    | { kind: "error"; message: string }
    | { kind: "sent"; status: PostReceipt["status"] }
  >({ kind: "idle" });
  const sending = useRef(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (sending.current) return;
    const problem = writeProblem(body, confirmed);
    if (problem) return setState({ kind: "error", message: problem });
    sending.current = true;
    setState({ kind: "sending" });
    const response = await apiFetch(
      `/forum/threads/${threadId}/posts`,
      account.token,
      { method: "POST", body: JSON.stringify({ body, anonymous }) },
    ).catch(() => null);
    sending.current = false;
    if (!response?.ok) {
      return setState({
        kind: "error",
        message: errorMessage(
          response?.status ?? null,
          "reply",
          retryAfterOf(response),
        ),
      });
    }
    const receipt: PostReceipt = await response.json();
    setBody("");
    setConfirmed(false);
    setState({ kind: "sent", status: receipt.status });
    onPosted();
  }

  const error = state.kind === "error" ? state.message : null;
  return (
    <form className="comment-form" onSubmit={submit} noValidate>
      <h3>回覆</h3>
      <label htmlFor="reply-body">你的回覆</label>
      <textarea
        id="reply-body"
        rows={5}
        value={body}
        aria-invalid={error !== null && bodyError(body) !== null}
        aria-describedby="reply-help"
        onChange={(event) => {
          setBody(event.target.value);
          if (state.kind !== "sending") setState({ kind: "idle" });
        }}
      />
      <p id="reply-help" className="note">
        {[...body].length} / {BODY_MAX} 字。純文字，不支援粗體或連結格式。
      </p>
      <PostFields
        idPrefix="reply"
        name={account.displayName ?? ""}
        anonymous={anonymous}
        setAnonymous={setAnonymous}
        confirmed={confirmed}
        setConfirmed={setConfirmed}
      />
      <button
        className="btn btn--primary"
        type="submit"
        disabled={state.kind === "sending"}
      >
        {state.kind === "sending" ? "送出中…" : "送出回覆"}
      </button>
      <div aria-live="polite">
        {error && (
          <p className="callout" role="alert">
            {error}
          </p>
        )}
        {state.kind === "sent" && (
          <p className="callout">{receiptMessage(state.status)}</p>
        )}
      </div>
    </form>
  );
}

function PostItem({
  post,
  title,
  account,
  onChanged,
  onDeleted,
}: {
  post: Reply | OpeningPost;
  title?: string;
  account: SignedIn;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const [mode, setMode] = useState<"view" | "edit" | "delete" | "report">(
    "view",
  );
  const [draft, setDraft] = useState(post.body);
  const [draftTitle, setDraftTitle] = useState(title ?? "");
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
    if (busy) return false;
    setBusy(true);
    const response = await apiFetch(path, account.token, init).catch(
      () => null,
    );
    setBusy(false);
    if (response?.ok) return true;
    setMessage({
      text: errorMessage(
        response?.status ?? null,
        action,
        retryAfterOf(response),
      ),
      error: true,
    });
    return false;
  }

  async function saveEdit(event: React.FormEvent) {
    event.preventDefault();
    const problem =
      (title !== undefined ? titleError(draftTitle) : null) ?? bodyError(draft);
    if (problem) return setMessage({ text: problem, error: true });
    const ok = await send("edit", `/forum/posts/${post.id}`, {
      method: "PATCH",
      body: JSON.stringify(
        title !== undefined
          ? { body: draft, title: draftTitle.trim() }
          : { body: draft },
      ),
    });
    if (ok) {
      setMode("view");
      setMessage(null);
      onChanged();
    }
  }

  async function remove() {
    if (await send("delete", `/forum/posts/${post.id}`, { method: "DELETE" }))
      onDeleted();
  }

  async function report(event: React.FormEvent) {
    event.preventDefault();
    if (!reason.trim())
      return setMessage({ text: "請寫下檢舉原因", error: true });
    const ok = await send("report", `/forum/posts/${post.id}/reports`, {
      method: "POST",
      body: JSON.stringify({ reason: reason.trim() }),
    });
    if (ok) {
      setMode("view");
      setReason("");
      setMessage({ text: "已收到檢舉，維護者會處理。", error: false });
    }
  }

  const edited = post.updatedAt !== post.createdAt;
  return (
    <li className="comment">
      <p className="comment__meta">
        <span className="comment__author">{authorName(post)}</span>
        {post.ai && <AiChip label="AI" />}
        {post.mine && <span className="chip">你的貼文</span>}
        <time dateTime={post.createdAt}>{postDate(post.createdAt)}</time>
        {edited && <span>（已編輯）</span>}
      </p>
      {mode === "edit" ? (
        <form className="comment-form" onSubmit={saveEdit} noValidate>
          {title !== undefined && (
            <>
              <label htmlFor={`edit-title-${post.id}`}>修改標題</label>
              <input
                id={`edit-title-${post.id}`}
                className="forum-input"
                value={draftTitle}
                onChange={(event) => setDraftTitle(event.target.value)}
              />
            </>
          )}
          <label htmlFor={`edit-${post.id}`}>修改內容</label>
          <textarea
            id={`edit-${post.id}`}
            rows={6}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <p className="note">{DEIDENTIFY}</p>
          <div className="comment__actions">
            <button className="btn btn--primary" type="submit" disabled={busy}>
              儲存
            </button>
            <button
              className="btn btn--quiet"
              type="button"
              onClick={() => {
                setMode("view");
                setDraft(post.body);
                setDraftTitle(title ?? "");
                setMessage(null);
              }}
            >
              取消
            </button>
          </div>
        </form>
      ) : (
        <p className="comment__body">{post.body}</p>
      )}
      <LikeButton
        // Remount when the server's numbers change, so a refresh replaces any optimistic state.
        key={`${post.likeCount}-${post.liked}`}
        postId={post.id}
        count={post.likeCount}
        liked={post.liked}
        canLike={!post.mine}
        token={account.token}
      />
      {mode === "view" && (
        <div className="comment__actions">
          {post.mine ? (
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
          <p>
            {title !== undefined
              ? "確定刪除這個話題？刪除後整串回覆都會消失，無法復原。"
              : "確定刪除這則回覆？刪除後無法復原。"}
          </p>
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
          <label htmlFor={`report-${post.id}`}>檢舉原因</label>
          <textarea
            id={`report-${post.id}`}
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
  postId,
  count,
  liked,
  canLike,
  token,
}: {
  postId: string;
  count: number;
  liked: boolean;
  canLike: boolean;
  token: string;
}) {
  const [state, setState] = useState({ likeCount: count, liked });
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
    setState({ liked: next, likeCount: before.likeCount + (next ? 1 : -1) });
    setBusy(true);
    setError(null);
    const response = await apiFetch(`/forum/posts/${postId}/likes`, token, {
      method: next ? "PUT" : "DELETE",
    }).catch(() => null);
    setBusy(false);
    if (response?.ok) return setState(await response.json());
    setState(before);
    setError(
      errorMessage(response?.status ?? null, "like", retryAfterOf(response)),
    );
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
