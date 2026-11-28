"use client";

// The colorectal surgeon forum (H7 #129, ADR-0022). Everything here runs in the browser, so the page HTML is the same
// for everyone and holds no forum content (ADR-0020); the API answers forum requests only for verified members and
// gives everyone else 404. Which posts are the member's own comes from the API's `mine`, never from names.
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useAccount, type Account } from "@/components/account";
import { Avatar } from "@/components/avatar";
import { AiChip, Icon } from "@/components/reading";
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
  relativeTime,
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

function GateCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="forum-gate">
      <div className="forum-gate__body">
        <p className="forum-gate__kicker">醫師會員限定</p>
        <p>{ABOUT}</p>
        <div className="forum-gate__action">{children}</div>
      </div>
      <ol className="forum-gate__steps" aria-label="加入與使用流程">
        <li>
          <span className="forum-gate__num" aria-hidden="true">
            01
          </span>
          <div>
            <strong>以 Email 或 Google 登入</strong>
            <span>無須密碼，首次登入自訂公開顯示名稱。</span>
          </div>
        </li>
        <li>
          <span className="forum-gate__num" aria-hidden="true">
            02
          </span>
          <div>
            <strong>完成大腸直腸外科身分驗證</strong>
            <span>醫院信箱自動核可，或於帳號設定提交專科／受訓資料。</span>
          </div>
        </li>
        <li>
          <span className="forum-gate__num" aria-hidden="true">
            03
          </span>
          <div>
            <strong>私密討論・去識別化原則</strong>
            <span>可選擇署名或匿名；內容不公開、不被搜尋引擎收錄。</span>
          </div>
        </li>
      </ol>
    </div>
  );
}

function ForumFeedSkeleton({ label = "載入話題中…" }: { label?: string }) {
  return (
    <div className="forum-skeleton" role="status" aria-live="polite">
      <span className="visually-hidden">{label}</span>
      {[0, 1].map((item) => (
        <div className="forum-skeleton__card" aria-hidden="true" key={item}>
          <div className="forum-skeleton__head">
            <span className="forum-skeleton__avatar" />
            <div className="forum-skeleton__meta">
              <span className="forum-skeleton__line forum-skeleton__line--short" />
              <span className="forum-skeleton__line forum-skeleton__line--xs" />
            </div>
          </div>
          <span className="forum-skeleton__line forum-skeleton__line--title" />
          <span className="forum-skeleton__line" />
          <span className="forum-skeleton__line forum-skeleton__line--mid" />
        </div>
      ))}
    </div>
  );
}

function ForumSkeleton() {
  return (
    <div className="forum-layout" role="status" aria-live="polite">
      <span className="visually-hidden">載入中…</span>
      <div className="forum-layout__main" aria-hidden="true">
        <div className="forum-skeleton__card forum-skeleton__card--composer">
          <div className="forum-skeleton__head">
            <span className="forum-skeleton__avatar" />
            <span className="forum-skeleton__input" />
          </div>
        </div>
        <div className="forum-skeleton">
          {[0, 1].map((item) => (
            <div className="forum-skeleton__card" key={item}>
              <div className="forum-skeleton__head">
                <span className="forum-skeleton__avatar" />
                <div className="forum-skeleton__meta">
                  <span className="forum-skeleton__line forum-skeleton__line--short" />
                  <span className="forum-skeleton__line forum-skeleton__line--xs" />
                </div>
              </div>
              <span className="forum-skeleton__line forum-skeleton__line--title" />
              <span className="forum-skeleton__line" />
              <span className="forum-skeleton__line forum-skeleton__line--mid" />
            </div>
          ))}
        </div>
      </div>
      <aside className="forum-layout__rail" aria-hidden="true">
        <div className="forum-skeleton__card">
          <span className="forum-skeleton__line forum-skeleton__line--short" />
          <span className="forum-skeleton__line" />
          <span className="forum-skeleton__line forum-skeleton__line--mid" />
        </div>
      </aside>
    </div>
  );
}

/** Renders its children only for verified members; everyone else gets the explanation and the next step. */
function MembersOnly({
  children,
}: {
  children: (account: SignedIn, membership: Membership) => React.ReactNode;
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
  if (account.status === "loading") return <ForumSkeleton />;
  if (account.status === "unavailable")
    return <p role="alert">目前無法連線到帳號服務，請稍後再試。</p>;
  if (account.status === "signed-out") {
    return (
      <GateCard>
        <Link
          className="btn btn--primary"
          href={`/login/?next=${encodeURIComponent(returnPath(path))}`}
        >
          登入
        </Link>
      </GateCard>
    );
  }
  if (!account.displayName) {
    return (
      <GateCard>
        <p>
          請先
          <Link href="/account/?welcome=1&next=%2Faccount%2F">
            設定顯示名稱
          </Link>
          ，再申請驗證。
        </p>
      </GateCard>
    );
  }
  if (membership?.user !== user) return <ForumSkeleton />;
  if (membership.value === null)
    return <p role="alert">暫時無法確認會員資格，請稍後再試。</p>;
  if (membership.value.status !== "verified") {
    return (
      <GateCard>
        <p>
          {membership.value.status === "pending"
            ? "你的驗證申請正在審核中，開通後就能進入論壇。"
            : "你還不是大腸直腸外科會員。"}{" "}
          <Link href="/account/">到帳號設定查看或申請</Link>
        </p>
      </GateCard>
    );
  }
  return children(account, membership.value);
}

// --- the thread feed ---------------------------------------------------------------------------------------------

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
      {(account, membership) => (
        <Threads account={account} membership={membership} topics={topics} />
      )}
    </MembersOnly>
  );
}

function TopicFilterBar({
  topics,
  active,
  onSelect,
}: {
  topics: TopicLabel[];
  active: string;
  onSelect: (key: string) => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState({ start: false, end: false });
  const options = [{ key: "all", label: "全部討論" }, ...topics];
  const selectedIndex = Math.max(
    0,
    options.findIndex((o) => o.key === active),
  );

  useEffect(() => {
    const node = track.current;
    if (!node) return;
    const measure = () => {
      const start = node.scrollLeft > 2;
      const end = node.scrollWidth - node.clientWidth - node.scrollLeft > 2;
      setFade((prev) =>
        prev.start === start && prev.end === end ? prev : { start, end },
      );
    };
    measure();
    node.addEventListener("scroll", measure, { passive: true });
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    observer?.observe(node);
    return () => {
      node.removeEventListener("scroll", measure);
      observer?.disconnect();
    };
  }, [options.length]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const last = options.length - 1;
    const next =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? selectedIndex === last
          ? 0
          : selectedIndex + 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? selectedIndex === 0
            ? last
            : selectedIndex - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : -1;
    if (next < 0 || !options[next]) return;
    event.preventDefault();
    const targetKey = options[next].key;
    onSelect(targetKey);
    const button = track.current?.querySelector<HTMLElement>(
      `[data-topic-key="${CSS.escape(targetKey)}"]`,
    );
    button?.focus();
  }

  return (
    <div
      className="filter-bar forum-filter"
      data-fade-start={fade.start || undefined}
      data-fade-end={fade.end || undefined}
    >
      <div
        ref={track}
        className="filter-bar__track"
        role="group"
        aria-label="依臨床主題篩選討論"
      >
        {options.map((opt, index) => (
          <button
            key={opt.key}
            type="button"
            className="filter-tab"
            data-topic-key={opt.key}
            aria-pressed={active === opt.key}
            tabIndex={index === selectedIndex ? 0 : -1}
            onClick={() => onSelect(opt.key)}
            onKeyDown={onKeyDown}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Threads({
  account,
  membership,
  topics,
}: {
  account: SignedIn;
  membership: Membership;
  topics: TopicLabel[];
}) {
  const [list, setList] = useState<List>({ kind: "loading" });
  const [own, setOwn] = useState<OwnPost[]>([]);
  const [activeTopic, setActiveTopic] = useState("all");
  const [version, setVersion] = useState(0);
  const token = account.token;

  const loadPage = useCallback(
    async (cursor: string | null, topicKey: string): Promise<ThreadPage> => {
      const query = new URLSearchParams({ limit: "20" });
      if (cursor) query.set("cursor", cursor);
      if (topicKey !== "all") query.set("topic", topicKey);
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
    loadPage(null, activeTopic).then(
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
    return () => {
      live = false;
    };
  }, [loadPage, activeTopic, version]);

  useEffect(() => {
    let live = true;
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
  }, [account.userId, version]);

  function selectTopic(key: string) {
    if (key === activeTopic) return;
    setActiveTopic(key);
    setList({ kind: "loading" });
  }

  async function more() {
    if (list.kind !== "ready" || !list.next) return;
    try {
      const page = await loadPage(list.next, activeTopic);
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
  const myName = account.displayName ?? "";
  return (
    <div className="forum-layout">
      <div className="forum-layout__main">
        {/* Facebook-style composer card leading into /forum/new/ */}
        <section className="composer-card" aria-label="快速發文">
          <div className="composer-card__top">
            <Avatar name={myName} size="md" />
            <Link className="composer-card__trigger" href="/forum/new/">
              {myName}，想和同儕分享臨床觀察或討論案例嗎？
            </Link>
          </div>
          <div className="composer-card__bar">
            <Link className="composer-card__shortcut" href="/forum/new/">
              <Icon name="edit" />
              發起臨床討論
            </Link>
            <Link
              className="composer-card__shortcut"
              href="/forum/new/?anonymous=1"
            >
              <Icon name="shield" />
              匿名提問
            </Link>
            <span className="composer-card__hint">請維持去識別化原則</span>
          </div>
        </section>

        {topics.length > 0 && (
          <TopicFilterBar
            topics={topics}
            active={activeTopic}
            onSelect={selectTopic}
          />
        )}

        {list.kind === "loading" && <ForumFeedSkeleton />}
        {list.kind === "error" && (
          <p className="forum-status" role="alert">
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
              <ul className="forum-feed" aria-label="置頂話題">
                {list.pinned.map((thread) => (
                  <FeedCard
                    key={thread.id}
                    thread={thread}
                    labels={labels}
                    token={token}
                  />
                ))}
              </ul>
            )}
            {list.items.length === 0 && list.pinned.length === 0 ? (
              <div className="empty-state">
                <p>
                  {activeTopic === "all"
                    ? "還沒有話題。"
                    : `「${labels.get(activeTopic) ?? activeTopic}」目前還沒有討論。`}
                </p>
                <div className="comment__actions">
                  <Link className="btn btn--primary" href="/forum/new/">
                    開第一個話題
                  </Link>
                  {activeTopic !== "all" && (
                    <button
                      className="btn btn--secondary"
                      type="button"
                      onClick={() => selectTopic("all")}
                    >
                      顯示全部討論
                    </button>
                  )}
                </div>
              </div>
            ) : (
              list.items.length > 0 && (
                <ul className="forum-feed" aria-label="話題">
                  {list.items.map((thread) => (
                    <FeedCard
                      key={thread.id}
                      thread={thread}
                      labels={labels}
                      token={token}
                    />
                  ))}
                </ul>
              )
            )}
            {list.next && (
              <div className="forum-feed__more">
                <button
                  className="btn btn--secondary"
                  type="button"
                  onClick={more}
                >
                  載入更多話題
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <aside className="forum-layout__rail" aria-label="發文與社群資訊">
        <Link className="btn btn--primary forum-layout__cta" href="/forum/new/">
          開新話題
        </Link>

        <section className="forum-member-card" aria-label="你的會員身分">
          <div className="forum-member-card__head">
            <Avatar name={myName} size="md" />
            <div className="forum-member-card__info">
              <strong>{myName}</strong>
              <span className="forum-member-card__badge">
                <Icon name="shield" />
                大腸直腸外科會員
              </span>
            </div>
          </div>
          {membership.since && (
            <p className="note">驗證於 {postDate(membership.since)}</p>
          )}
          <Link className="forum-member-card__link" href="/account/">
            前往個人儀表板 →
          </Link>
        </section>

        <ForumRules />

        {own.length > 0 && (
          <section className="forum-own-panel" aria-labelledby="forum-own">
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
                    <time
                      dateTime={item.post.createdAt}
                      title={postDate(item.post.createdAt)}
                    >
                      {relativeTime(item.post.createdAt)}
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

function FeedCard({
  thread,
  labels,
  token,
}: {
  thread: ThreadSummary;
  labels: Map<string, string>;
  token: string;
}) {
  const topic = thread.topicKey ? labels.get(thread.topicKey) : undefined;
  const author = authorName(thread);
  const href = threadPath(thread.id);
  const preview = thread.bodyPreview;
  const latest = thread.latestReply;

  return (
    <li
      className={`forum-row feed-card${thread.pinned ? " feed-card--pinned" : ""}`}
    >
      <header className="feed-card__header">
        <Avatar
          name={thread.displayName}
          anonymous={thread.anonymous}
          ai={thread.ai}
          size="md"
        />
        <div className="feed-card__author-block">
          <div className="feed-card__author-line">
            <span className="comment__author">{author}</span>
            {thread.ai && <AiChip label="AI" />}
            {thread.mine && <span className="chip">你的貼文</span>}
            {thread.pinned && (
              <span className="chip chip--pin">
                <Icon name="pin" />
                置頂
              </span>
            )}
          </div>
          <p className="feed-card__submeta">
            <time
              dateTime={thread.createdAt}
              title={postDate(thread.createdAt)}
            >
              {relativeTime(thread.createdAt)}
            </time>
            {!thread.ai && !thread.anonymous && <span>大腸直腸外科會員</span>}
            {topic && <span className="feed-card__topic">{topic}</span>}
          </p>
        </div>
      </header>

      <div className="feed-card__body">
        <Link className="forum-thread__title feed-card__title" href={href}>
          {thread.title}
        </Link>
        {preview && <p className="feed-card__preview">{preview}</p>}
        {thread.paperId && (
          <Link
            className="feed-card__paper"
            href={paperPathFromId(thread.paperId)}
          >
            <Icon name="book" />
            <span>連結文獻：{thread.paperId}</span>
          </Link>
        )}
      </div>

      <div className="feed-card__footer">
        <div className="feed-card__actions">
          <LikeButton
            key={`${thread.id}-${thread.likeCount}-${Boolean(thread.liked)}`}
            postId={thread.id}
            count={thread.likeCount}
            liked={Boolean(thread.liked)}
            canLike={!thread.mine}
            token={token}
          />
          <Link
            className="btn btn--quiet feed-card__action-btn"
            href={`${href}#forum-replies`}
          >
            <Icon name="chat" />
            <span>
              {thread.replyCount > 0
                ? `${thread.replyCount} 則回覆`
                : "回覆討論"}
            </span>
          </Link>
        </div>
        <span className="feed-card__activity">
          {thread.lastReplyAt ? (
            <>
              最新回覆{" "}
              <time
                dateTime={thread.lastReplyAt}
                title={postDate(thread.lastReplyAt)}
              >
                {relativeTime(thread.lastReplyAt)}
              </time>
            </>
          ) : (
            "尚無回覆"
          )}
        </span>
      </div>

      {latest && (
        <div className="feed-card__latest">
          <Avatar
            name={latest.displayName}
            anonymous={latest.anonymous}
            ai={latest.ai}
            size="xs"
          />
          <div className="feed-card__latest-bubble">
            <p className="feed-card__latest-meta">
              <strong>{authorName(latest)}</strong>
              {latest.ai && <AiChip label="AI" />}
              <time
                dateTime={latest.createdAt}
                title={postDate(latest.createdAt)}
              >
                {relativeTime(latest.createdAt)}
              </time>
            </p>
            <p className="feed-card__latest-text">{latest.bodyPreview}</p>
            {thread.replyCount > 1 && (
              <Link className="feed-card__latest-more" href={href}>
                查看全部 {thread.replyCount} 則回覆 →
              </Link>
            )}
          </div>
        </div>
      )}
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
  confirmRef,
}: {
  idPrefix: string;
  name: string;
  anonymous: boolean;
  setAnonymous: (value: boolean) => void;
  confirmed: boolean;
  setConfirmed: (value: boolean) => void;
  confirmRef?: React.RefObject<HTMLInputElement | null>;
}) {
  return (
    <>
      <fieldset className="comment-form__identity">
        <legend>顯示方式</legend>
        <label className="identity-option">
          <input
            type="radio"
            name={`${idPrefix}-identity`}
            checked={!anonymous}
            onChange={() => setAnonymous(false)}
          />
          <span>署名，顯示為「{name}」</span>
        </label>
        <label className="identity-option">
          <input
            type="radio"
            name={`${idPrefix}-identity`}
            checked={anonymous}
            onChange={() => setAnonymous(true)}
          />
          <span>
            匿名：其他會員看不到你的名稱；你本人和維護者仍能對應到你的帳號
          </span>
        </label>
      </fieldset>
      <div className="callout forum-deidentify" id={`${idPrefix}-deidentify`}>
        <p>{DEIDENTIFY}</p>
        <label className="forum-deidentify__check">
          <input
            ref={confirmRef}
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>我確認內容不含可識別病人的資訊</span>
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
  const searchParams = useSearchParams();
  const paperId = paperIdParam(searchParams.get("paperId"));
  const initialAnonymous = searchParams.get("anonymous") === "1";
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [topic, setTopic] = useState("");
  const [anonymous, setAnonymous] = useState(initialAnonymous);
  const [confirmed, setConfirmed] = useState(false);
  const [state, setState] = useState<
    | { kind: "idle" | "sending" }
    | { kind: "error"; message: string }
    | { kind: "pending" }
  >({ kind: "idle" });
  const sending = useRef(false);
  const titleField = useRef<HTMLInputElement>(null);
  const bodyField = useRef<HTMLTextAreaElement>(null);
  const confirmField = useRef<HTMLInputElement>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (sending.current) return;
    const problem = writeProblem(body, confirmed, title);
    if (problem) {
      setState({ kind: "error", message: problem });
      if (titleError(title)) titleField.current?.focus();
      else if (bodyError(body)) bodyField.current?.focus();
      else confirmField.current?.focus();
      return;
    }
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
      <div className="forum-composer-card" aria-live="polite">
        <p className="callout">{receiptMessage("pending")}</p>
        <div className="comment__actions">
          <Link className="btn btn--secondary" href="/forum/">
            回論壇
          </Link>
        </div>
      </div>
    );
  }

  const error = state.kind === "error" ? state.message : null;
  const displayName = account.displayName ?? "";
  return (
    <div className="split">
      <div className="forum-composer-card">
        <div className="forum-composer-card__author">
          <Avatar name={displayName} anonymous={anonymous} size="md" />
          <div>
            <strong>{anonymous ? "匿名醫師" : displayName}</strong>
            <span className="note">
              {anonymous
                ? "匿名發表・僅你與維護者可對應帳號"
                : "署名發表・大腸直腸外科會員"}
            </span>
          </div>
        </div>

        <form
          className="comment-form forum-composer-form"
          onSubmit={submit}
          noValidate
        >
          {paperId && (
            <p className="feed-card__paper">
              <Icon name="book" />
              <span>
                這個話題會連結到文獻：
                <Link href={paperPathFromId(paperId)}>{paperId}</Link>
              </span>
            </p>
          )}
          <div className="forum-field">
            <label htmlFor="thread-title">標題</label>
            <input
              ref={titleField}
              id="thread-title"
              className="forum-input"
              placeholder="例：低位直腸癌 TNT 後 cCR 的追蹤節奏討論"
              value={title}
              aria-invalid={error !== null && titleError(title) !== null}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="forum-field">
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
          </div>
          <div className="forum-field">
            <label htmlFor="thread-body">內容</label>
            <textarea
              ref={bodyField}
              id="thread-body"
              rows={8}
              placeholder="分享你的臨床經驗、疑問或文獻觀察（請改寫為年齡區間與必要臨床資訊）…"
              value={body}
              aria-invalid={error !== null && bodyError(body) !== null}
              aria-describedby="thread-help"
              onChange={(event) => setBody(event.target.value)}
            />
            <p id="thread-help" className="note">
              {[...body].length} / {BODY_MAX} 字。純文字，不支援粗體或連結格式。
            </p>
          </div>
          <PostFields
            idPrefix="thread"
            name={displayName}
            anonymous={anonymous}
            setAnonymous={setAnonymous}
            confirmed={confirmed}
            setConfirmed={setConfirmed}
            confirmRef={confirmField}
          />
          <div className="forum-composer-form__actions">
            <button
              className="btn btn--primary"
              type="submit"
              disabled={state.kind === "sending"}
            >
              {state.kind === "sending" ? "送出中…" : "發表話題"}
            </button>
            <Link className="btn btn--quiet" href="/forum/">
              回論壇
            </Link>
          </div>
          <div aria-live="polite">
            {error && (
              <p className="callout" role="alert">
                {error}
              </p>
            )}
          </div>
        </form>
      </div>
      <aside className="split__rail" aria-label="發文指引">
        <ForumRules />
        <section className="forum-tips" aria-labelledby="forum-tips-title">
          <h2 id="forum-tips-title">臨床討論小提醒</h2>
          <ul>
            <li>清楚描述分期、分子狀態與治療線別，方便同儕快速對焦。</li>
            <li>若針對特定試驗或指引討論，可在上方選取對應臨床主題。</li>
            <li>首次在論壇發文須經維護者核准，通過後即可即時發布。</li>
          </ul>
        </section>
      </aside>
    </div>
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
      <div className="empty-state">
        <h1>找不到這個話題</h1>
        <p>話題可能已被作者刪除或由維護者隱藏。</p>
        <Link className="btn btn--secondary" href="/forum/">
          回論壇
        </Link>
      </div>
    );
  }
  const { thread } = detail;
  const topic = topics.find((t) => t.key === thread.topicKey)?.label;
  return (
    <>
      <header className="page-head thread-head">
        <p className="comment__meta">
          <Link className="thread-head__back" href="/forum/">
            ← 回醫師論壇
          </Link>
          {thread.pinned && (
            <span className="chip chip--pin">
              <Icon name="pin" />
              置頂
            </span>
          )}
          {topic && <span className="chip">{topic}</span>}
          {thread.paperId && (
            <Link
              className="thread-head__paper"
              href={paperPathFromId(thread.paperId)}
            >
              相關文獻
            </Link>
          )}
        </p>
        <h1>{thread.title}</h1>
      </header>
      <div className="split">
        <div className="thread-stream">
          <ul className="comment-list thread-op-list" aria-label="話題內容">
            <PostItem
              post={thread}
              title={thread.title}
              replyCount={detail.replies.length}
              hasMoreReplies={Boolean(detail.next)}
              paperId={thread.paperId}
              variant="opening"
              account={account}
              onChanged={refresh}
              onDeleted={() => router.push("/forum/")}
            />
          </ul>
          <section className="thread-replies" aria-labelledby="forum-replies">
            <div className="thread-replies__head">
              <h2 id="forum-replies">
                回覆
                <span className="thread-replies__count">
                  {detail.replies.length + (detail.next ? "+" : "")}
                </span>
              </h2>
            </div>
            {detail.replies.length > 0 ? (
              <ul className="comment-list reply-list" aria-label="回覆">
                {detail.replies.map((reply) => (
                  <PostItem
                    key={reply.id}
                    post={reply}
                    variant="reply"
                    account={account}
                    onChanged={refresh}
                    onDeleted={refresh}
                  />
                ))}
              </ul>
            ) : (
              <p className="note thread-replies__empty">
                還沒有回覆，歡迎在下方分享你的臨床經驗。
              </p>
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
                  <li className="comment reply-bubble" key={item.post.id}>
                    <div className="reply-bubble__row">
                      <Avatar
                        name={item.post.displayName}
                        anonymous={item.post.anonymous}
                        ai={item.post.ai}
                        size="sm"
                      />
                      <div className="reply-bubble__main">
                        <div className="reply-bubble__surface">
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
                        </div>
                        <DeleteButton
                          postId={item.post.id}
                          token={token}
                          onDeleted={refresh}
                        />
                      </div>
                    </div>
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
            <a className="btn btn--primary" href="#reply-body">
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
  const bodyField = useRef<HTMLTextAreaElement>(null);
  const confirmField = useRef<HTMLInputElement>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (sending.current) return;
    const problem = writeProblem(body, confirmed);
    if (problem) {
      setState({ kind: "error", message: problem });
      if (bodyError(body)) bodyField.current?.focus();
      else confirmField.current?.focus();
      return;
    }
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
  const displayName = account.displayName ?? "";
  return (
    <form className="comment-form reply-composer" onSubmit={submit} noValidate>
      <div className="reply-composer__head">
        <Avatar name={displayName} anonymous={anonymous} size="sm" />
        <h3>回覆</h3>
      </div>
      <label htmlFor="reply-body">你的回覆</label>
      <textarea
        ref={bodyField}
        id="reply-body"
        rows={4}
        placeholder="寫下你的臨床看法或補充經驗…"
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
        name={displayName}
        anonymous={anonymous}
        setAnonymous={setAnonymous}
        confirmed={confirmed}
        setConfirmed={setConfirmed}
        confirmRef={confirmField}
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
  replyCount,
  hasMoreReplies,
  paperId,
  variant = "reply",
  account,
  onChanged,
  onDeleted,
}: {
  post: Reply | OpeningPost;
  title?: string;
  replyCount?: number;
  hasMoreReplies?: boolean;
  paperId?: string | null;
  variant?: "opening" | "reply";
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
  const author = authorName(post);

  const editForm = (
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
  );

  const actionControls = (
    <div className="post-action-bar">
      <LikeButton
        // Remount when the server's numbers change, so a refresh replaces any optimistic state.
        key={`${post.likeCount}-${post.liked}`}
        postId={post.id}
        count={post.likeCount}
        liked={post.liked}
        canLike={!post.mine}
        token={account.token}
      />
      {variant === "opening" && replyCount !== undefined && (
        <a className="btn btn--quiet feed-card__action-btn" href="#reply-body">
          <Icon name="chat" />
          <span>
            {replyCount}
            {hasMoreReplies ? "+" : ""} 則回覆
          </span>
        </a>
      )}
      {mode === "view" && (
        <div className="comment__actions post-action-bar__end">
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
    </div>
  );

  const secondaryPanels = (
    <>
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
    </>
  );

  if (variant === "opening") {
    return (
      <li className="comment thread-op">
        <header className="feed-card__header">
          <Avatar
            name={post.displayName}
            anonymous={post.anonymous}
            ai={post.ai}
            size="md"
          />
          <div className="feed-card__author-block">
            <div className="feed-card__author-line">
              <span className="comment__author">{author}</span>
              {post.ai && <AiChip label="AI" />}
              {post.mine && <span className="chip">你的貼文</span>}
            </div>
            <p className="feed-card__submeta">
              <time dateTime={post.createdAt} title={postDate(post.createdAt)}>
                {relativeTime(post.createdAt)} · {postDate(post.createdAt)}
              </time>
              {edited && <span>（已編輯）</span>}
            </p>
          </div>
        </header>
        {mode === "edit" ? (
          editForm
        ) : (
          <p className="comment__body thread-op__body">{post.body}</p>
        )}
        {paperId && mode === "view" && (
          <Link className="feed-card__paper" href={paperPathFromId(paperId)}>
            <Icon name="book" />
            <span>查看關聯文獻：{paperId}</span>
          </Link>
        )}
        {actionControls}
        {secondaryPanels}
      </li>
    );
  }

  return (
    <li className="comment reply-bubble">
      <div className="reply-bubble__row">
        <Avatar
          name={post.displayName}
          anonymous={post.anonymous}
          ai={post.ai}
          size="sm"
        />
        <div className="reply-bubble__main">
          <div className="reply-bubble__surface">
            <p className="comment__meta">
              <span className="comment__author">{author}</span>
              {post.ai && <AiChip label="AI" />}
              {post.mine && <span className="chip">你的貼文</span>}
              <time dateTime={post.createdAt} title={postDate(post.createdAt)}>
                {relativeTime(post.createdAt)}
              </time>
              {edited && <span>（已編輯）</span>}
            </p>
            {mode === "edit" ? (
              editForm
            ) : (
              <p className="comment__body">{post.body}</p>
            )}
          </div>
          {actionControls}
          {secondaryPanels}
        </div>
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
      <p className="comment__likes comment__likes--readonly">
        <Icon name="thumb" />
        <span>{state.likeCount} 個讚</span>
      </p>
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
        className="btn btn--quiet feed-card__action-btn"
        type="button"
        aria-pressed={state.liked}
        onClick={toggle}
      >
        <Icon name="thumb" />
        <span>
          讚<span aria-hidden="true">・{state.likeCount}</span>
        </span>
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
