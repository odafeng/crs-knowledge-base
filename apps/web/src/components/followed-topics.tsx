"use client";

// Followed topics (G6 #117): chosen on the account page, shown on the home page. Both read the private /me/topics
// in the browser; the server-rendered HTML is the same for everyone.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/account";
import { retryAfterOf } from "@/lib/comments";
import {
  followedUpdates,
  loadTopics,
  saveTopics,
  type FollowRow,
} from "@/lib/followed";

type Choice = { key: string; label: string };

export function TopicChoices({ topics }: { topics: Choice[] }) {
  const account = useAccount();
  const signedIn = account.status === "signed-in" ? account : null;
  const token = signedIn?.token;
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!token || !signedIn?.displayName) return;
    let live = true;
    loadTopics(token).then((loaded) => {
      if (!live) return;
      if (loaded) setChosen(new Set(loaded));
      else setStatus("暫時無法載入訂閱主題，請稍後再試。");
    });
    return () => {
      live = false;
    };
    // Load once per account; hourly token refreshes do not change the choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn?.userId, signedIn?.displayName]);

  if (!signedIn?.displayName || chosen === null) return null;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!token || !chosen) return;
    setSaving(true);
    const response = await saveTopics(token, [...chosen]);
    setSaving(false);
    if (response?.ok)
      return setStatus("已儲存。首頁會列出這些主題的最新文獻。");
    setStatus(
      response?.status === 503 && retryAfterOf(response)
        ? "網站維護中，暫時無法儲存，請稍後再試。"
        : "儲存失敗，請稍後再試。",
    );
  }

  return (
    <form className="topic-choices" onSubmit={save}>
      <fieldset>
        <legend>訂閱主題</legend>
        <p className="note">
          只有你看得到自己訂了什麼。首頁會另外列出這些主題的最新文獻。
        </p>
        {topics.map((topic) => (
          <label className="topic-choices__item" key={topic.key}>
            <input
              type="checkbox"
              checked={chosen.has(topic.key)}
              onChange={(event) => {
                const next = new Set(chosen);
                if (event.target.checked) next.add(topic.key);
                else next.delete(topic.key);
                setChosen(next);
                setStatus("");
              }}
            />
            {topic.label}
          </label>
        ))}
      </fieldset>
      <button className="btn btn--secondary" type="submit" disabled={saving}>
        儲存訂閱主題
      </button>
      <p role="status">{status}</p>
    </form>
  );
}

export function FollowedUpdates({ rows }: { rows: FollowRow[] }) {
  const account = useAccount();
  const signedIn = account.status === "signed-in" ? account : null;
  const [topics, setTopics] = useState<string[] | null>(null);

  useEffect(() => {
    if (!signedIn?.displayName) return;
    let live = true;
    loadTopics(signedIn.token).then((loaded) => live && setTopics(loaded));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedIn?.userId, signedIn?.displayName]);

  const shown = topics ? followedUpdates(rows, topics, 5) : [];
  if (!signedIn || shown.length === 0) return null;
  return (
    <section className="band followed" aria-labelledby="followed-title">
      <div className="section-head">
        <h2 id="followed-title">你訂閱的主題</h2>
        <Link href="/account/">管理訂閱</Link>
      </div>
      <ul className="followed__list">
        {shown.map((row) => (
          <li key={row.path}>
            <Link href={row.path}>{row.title}</Link>
            <span className="followed__meta">
              {row.topicLabel}・<time dateTime={row.date}>{row.date}</time>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
