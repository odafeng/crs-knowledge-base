"use client";

// The maintainer's weekly activity page (G10 #121). Counts only: the API never lists who was active. The API decides
// who may see it (app.accounts.is_admin); this page only hides itself from everyone else.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount, type Account } from "@/components/account";
import { apiFetch, authEnabled } from "@/lib/auth";
import { errorMessage } from "@/lib/comments";
import { activityRows, activitySummary, type Week } from "@/lib/stats";

type SignedIn = Extract<Account, { status: "signed-in" }>;

export function ActivityStats() {
  const account = useAccount();
  if (!authEnabled) return <p>登入功能尚未開放。</p>;
  if (account.status === "loading") return <p aria-live="polite">載入中…</p>;
  if (account.status === "unavailable")
    return <p role="alert">目前無法連線到帳號服務，請稍後再試。</p>;
  if (account.status === "signed-out") {
    return (
      <p>
        請先<Link href="/login/?next=%2Fadmin%2Fstats%2F">登入</Link>。
      </p>
    );
  }
  if (!account.isAdmin) return <p role="alert">需要管理者權限。</p>;
  return <Weeks account={account} />;
}

function Weeks({ account }: { account: SignedIn }) {
  const [weeks, setWeeks] = useState<Week[] | null>(null);
  const [failed, setFailed] = useState(false);
  const token = account.token;

  useEffect(() => {
    let live = true;
    apiFetch("/admin/stats/weekly", token)
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then(
        (data: { weeks: Week[] }) => live && setWeeks(data.weeks),
        () => live && setFailed(true),
      );
    return () => {
      live = false;
    };
    // Load once; hourly token refreshes do not change the counts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (failed) return <p role="alert">{errorMessage(null, "load")}</p>;
  if (weeks === null) return <p aria-live="polite">載入中…</p>;
  return (
    <>
      <p>{activitySummary(weeks)}</p>
      <div
        className="table-wrap"
        tabIndex={0}
        role="region"
        aria-label="每週活動表格，可左右捲動"
      >
        <table className="table activity">
          <caption>最近 12 週（台北時間，週一起算）</caption>
          <thead>
            <tr>
              <th scope="col">週</th>
              <th scope="col">活躍讀者</th>
              <th scope="col">新帳號</th>
              <th scope="col">留言</th>
              <th scope="col">讚</th>
            </tr>
          </thead>
          <tbody>
            {activityRows(weeks).map((row) => (
              <tr
                key={row.week}
                aria-current={row.current ? "date" : undefined}
              >
                <th scope="row">{row.label}</th>
                <td>
                  <span className="activity__count">{row.activeReaders}</span>
                  <span
                    className="activity__bar"
                    style={{ inlineSize: `${row.bar}%` }}
                    aria-hidden="true"
                  />
                </td>
                <td>{row.newAccounts}</td>
                <td>{row.comments}</td>
                <td>{row.likes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
