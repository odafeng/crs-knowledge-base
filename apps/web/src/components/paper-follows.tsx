"use client";

// Following papers for the daily comment digest (G8 #119): the button in a paper's discussion and the list on the
// account page. The API decides everything; these only show the state and change it.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/account";
import {
  followedPapers,
  loadFollows,
  setDigest,
  setFollow,
  type FollowedPaper,
  type Follows,
} from "@/lib/paper-follows";

function useFollows() {
  const account = useAccount();
  const signedIn =
    account.status === "signed-in" && account.displayName ? account : null;
  const [follows, setFollows] = useState<Follows | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!signedIn) return;
    let live = true;
    loadFollows(signedIn.token).then((loaded) => {
      if (!live) return;
      if (loaded) setFollows(loaded);
      else setFailed(true);
    });
    return () => {
      live = false;
    };
    // Load once per account; hourly token refreshes do not change what is followed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn?.userId, signedIn?.displayName]);

  return { token: signedIn?.token ?? null, follows, setFollows, failed };
}

/** In a paper's discussion: follow its new comments. Shown only to readers with an account. */
export function FollowPaper({
  paperId,
  posted,
}: {
  paperId: string;
  posted: number;
}) {
  const { token, follows, setFollows } = useFollows();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    // Commenting follows the paper on the server; show it without a reload.
    if (posted && follows && !follows.papers.includes(paperId))
      setFollows({ ...follows, papers: [paperId, ...follows.papers] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [posted]);

  if (!token || !follows) return null;
  const on = follows.papers.includes(paperId);

  async function toggle() {
    if (!token) return;
    setBusy(true);
    const next = await setFollow(token, paperId, !on);
    setBusy(false);
    if (!next) return setStatus("操作失敗，請稍後再試。");
    setFollows(next);
    setStatus(
      !on
        ? next.commentDigest
          ? "已追蹤。有新留言時，隔天早上會寄一封彙整信到你的登入信箱。"
          : "已追蹤。每日留言通知目前關閉，可以在帳號設定打開。"
        : "已取消追蹤。",
    );
  }

  return (
    <div className="follow-paper">
      <button
        className="btn btn--secondary"
        type="button"
        aria-pressed={on}
        disabled={busy}
        onClick={toggle}
      >
        {on ? "已追蹤新留言" : "追蹤新留言"}
      </button>
      <p role="status" className="note">
        {status}
      </p>
    </div>
  );
}

/** On the account page: the daily digest switch and every followed paper, each with a way to stop following it. */
export function FollowedPapers({ papers }: { papers: FollowedPaper[] }) {
  const { token, follows, setFollows, failed } = useFollows();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  if (failed)
    return (
      <section className="followed-papers" aria-labelledby="follows-title">
        <h2 id="follows-title">追蹤的文獻</h2>
        <p role="status">暫時無法載入追蹤的文獻，請稍後再試。</p>
      </section>
    );
  if (!token || !follows) return null;
  const shown = followedPapers(follows.papers, papers);

  async function change(
    run: Promise<Follows | null>,
    done: string,
    shown?: Follows,
  ) {
    // `shown` is the state to show while the request runs, so a checkbox moves when it is clicked.
    const before = follows;
    if (shown) setFollows(shown);
    setBusy(true);
    const next = await run;
    setBusy(false);
    if (!next) {
      setFollows(before);
      return setStatus("操作失敗，請稍後再試。");
    }
    setFollows(next);
    setStatus(done);
  }

  return (
    <section className="followed-papers" aria-labelledby="follows-title">
      <h2 id="follows-title">追蹤的文獻</h2>
      <p className="note">
        在文獻頁按「追蹤新留言」，或在那篇留言，就會追蹤。只有你看得到自己追蹤了哪些。
      </p>
      <label className="followed-papers__switch">
        <input
          type="checkbox"
          checked={follows.commentDigest}
          disabled={busy}
          onChange={(event) => {
            const enabled = event.target.checked;
            change(
              setDigest(token, enabled),
              enabled
                ? "已開啟每日留言通知。"
                : "已關閉每日留言通知，追蹤的文獻保留不變。",
              { ...follows, commentDigest: enabled },
            );
          }}
        />
        每天早上寄一封信，列出追蹤的文獻前一天有幾則新留言（不寫留言者是誰）
      </label>
      {shown.length === 0 ? (
        <p>還沒有追蹤任何文獻。</p>
      ) : (
        <ul className="followed-papers__list">
          {shown.map((paper) => (
            <li key={paper.id}>
              <Link href={`${paper.path}#discussion`}>{paper.title}</Link>
              <button
                className="btn btn--secondary"
                type="button"
                disabled={busy}
                onClick={() =>
                  change(
                    setFollow(token, paper.id, false),
                    `已取消追蹤「${paper.title}」。`,
                  )
                }
              >
                取消追蹤
                <span className="visually-hidden">「{paper.title}」</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p role="status">{status}</p>
    </section>
  );
}
