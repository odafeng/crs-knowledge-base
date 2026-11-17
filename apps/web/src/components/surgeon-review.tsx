"use client";

// The maintainer's review of colorectal surgeon applications (H5 #127). Check each one against the society's
// specialist list (specialists) or the health ministry's practitioner lookup (trainees), then approve or reject:
// either way the API deletes the details. Applications that matched both the doctor map and a hospital mailbox never
// get here (H10 #168); the hints below say which half was missing. The API decides who may see this page.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount, type Account } from "@/components/account";
import { apiFetch, authEnabled } from "@/lib/auth";

type SignedIn = Extract<Account, { status: "signed-in" }>;
type Application = {
  accountId: string;
  displayName: string;
  realName: string;
  hospital: string;
  department: string;
  certificateDigits: string;
  submittedAt: string;
  hospitalEmail: boolean;
  roster: "listed" | "unlisted" | "unavailable";
};
const ROSTER: Record<Application["roster"], string> = {
  listed: "有此人（姓名與院所相符）",
  unlisted: "查無",
  unavailable: "暫時讀不到醫師地圖",
};
type Member = { accountId: string; displayName: string; since: string };

async function fetchQueue(
  token: string,
): Promise<{ applications: Application[]; members: Member[] } | null> {
  const [a, m] = await Promise.all([
    apiFetch("/admin/surgeon-applications", token).catch(() => null),
    apiFetch("/admin/surgeons", token).catch(() => null),
  ]);
  if (!a?.ok || !m?.ok) return null;
  return {
    applications: (await a.json()).applications,
    members: (await m.json()).surgeons,
  };
}

export function SurgeonReview() {
  const account = useAccount();
  if (!authEnabled) return <p>登入功能尚未開放。</p>;
  if (account.status === "loading") return <p aria-live="polite">載入中…</p>;
  if (account.status === "unavailable")
    return <p role="alert">目前無法連線到帳號服務，請稍後再試。</p>;
  if (account.status === "signed-out")
    return (
      <p>
        請先<Link href="/login/?next=%2Fadmin%2Fsurgeons%2F">登入</Link>。
      </p>
    );
  if (!account.isAdmin) return <p role="alert">需要管理者權限。</p>;
  return <Queue account={account} />;
}

function Queue({ account }: { account: SignedIn }) {
  const token = account.token;
  const [applications, setApplications] = useState<Application[] | null>(null);
  const [members, setMembers] = useState<Member[] | null>(null);
  const [status, setStatus] = useState("");

  function show(queue: Awaited<ReturnType<typeof fetchQueue>>) {
    if (!queue) return setStatus("暫時無法載入，請稍後再試。");
    setApplications(queue.applications);
    setMembers(queue.members);
  }

  useEffect(() => {
    let live = true;
    fetchQueue(token).then((queue) => live && show(queue));
    return () => {
      live = false;
    };
    // Load once; hourly token refreshes do not change the queue.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function act(path: string, init: RequestInit, done: string) {
    const response = await apiFetch(path, token, init).catch(() => null);
    setStatus(response?.ok ? done : "操作失敗，請重新整理後再試。");
    show(await fetchQueue(token));
  }

  if (applications === null || members === null)
    return <p role="status">{status || "載入中…"}</p>;
  return (
    <>
      <section aria-labelledby="pending-title">
        <h2 id="pending-title">待審申請（{applications.length}）</h2>
        {applications.length === 0 ? (
          <p>目前沒有待審申請。</p>
        ) : (
          <ul className="review-queue">
            {applications.map((a) => (
              <li key={a.accountId}>
                <dl>
                  <dt>姓名</dt>
                  <dd>{a.realName}</dd>
                  <dt>執業院所</dt>
                  <dd>{a.hospital}</dd>
                  <dt>科別</dt>
                  <dd>{a.department}</dd>
                  <dt>證書後三碼</dt>
                  <dd>{a.certificateDigits}</dd>
                  <dt>顯示名稱</dt>
                  <dd>{a.displayName}</dd>
                  <dt>申請時間</dt>
                  <dd>{a.submittedAt.slice(0, 16).replace("T", " ")}</dd>
                  <dt>醫師地圖</dt>
                  <dd>{ROSTER[a.roster]}</dd>
                  <dt>院所信箱</dt>
                  <dd>
                    {a.hospitalEmail
                      ? "用該院信箱收信登入"
                      : "不是該院信箱，或非收信登入"}
                  </dd>
                </dl>
                <div className="review-actions" role="group">
                  <button
                    className="btn btn--primary"
                    type="button"
                    onClick={() =>
                      act(
                        `/admin/surgeon-applications/${a.accountId}`,
                        {
                          method: "POST",
                          body: JSON.stringify({ decision: "approve" }),
                        },
                        `已核准 ${a.displayName}，申請資料已刪除。`,
                      )
                    }
                  >
                    核准
                  </button>
                  <button
                    className="btn btn--secondary"
                    type="button"
                    onClick={() =>
                      act(
                        `/admin/surgeon-applications/${a.accountId}`,
                        {
                          method: "POST",
                          body: JSON.stringify({ decision: "reject" }),
                        },
                        `已退回 ${a.displayName}，申請資料已刪除。`,
                      )
                    }
                  >
                    退回
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="members-title">
        <h2 id="members-title">大腸直腸外科會員（{members.length}）</h2>
        <ul className="review-queue">
          {members.map((m) => (
            <li key={m.accountId}>
              <p>
                {m.displayName}・{m.since.slice(0, 10)} 起
              </p>
              <div className="review-actions">
                <button
                  className="btn btn--secondary"
                  type="button"
                  onClick={() =>
                    act(
                      `/admin/surgeons/${m.accountId}`,
                      { method: "DELETE" },
                      `已撤銷 ${m.displayName} 的會員資格。`,
                    )
                  }
                >
                  撤銷資格
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <p role="status">{status}</p>
    </>
  );
}
