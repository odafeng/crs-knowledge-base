"use client";

// The admin's queue of AI-unreviewed papers and stories (E7 #188): every "AI 未審" item on one page, each with the
// same buttons as its own page. The list is public content; only an admin sees the buttons and the queue.
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/account";
import { ReviewActions } from "@/components/review-actions";
import type { components } from "@/lib/api.generated";
import { apiFetch, authEnabled } from "@/lib/auth";
import type { Pending } from "@/lib/review";

type AdminNewsEvent = components["schemas"]["AdminNewsEvent"];
type NewsEventAction = "approve" | "reject" | "withdraw";

const KIND = { paper: "文獻", news: "消息" } as const;
const RISK_LABEL: Record<string, string> = {
  low: "低風險",
  medium: "中風險",
  high: "高風險",
  reject: "已攔截",
};

function NewsEventReviewCard({
  event,
  token,
}: {
  event: AdminNewsEvent;
  token: string;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function act(action: NewsEventAction) {
    setBusy(true);
    const response = await apiFetch("/admin/content-requests", token, {
      method: "POST",
      body: JSON.stringify({
        action,
        kind: "news_event",
        target: event.id,
        reason: reason.trim() || `admin ${action} via /admin/review`,
      }),
    }).catch(() => null);
    setBusy(false);
    if (response?.status === 202) {
      setMessage(
        `已送出「${action}」請求，將由單一內容寫入排程套用並更新快取。`,
      );
    } else {
      setMessage("送出失敗，請稍後再試。");
    }
  }

  return (
    <li className="entry">
      <p className="eyebrow">
        <span>Newsroom 事件</span>
        <span className="chip">
          {RISK_LABEL[event.riskTier] ?? event.riskTier}
        </span>
        <span>狀態：{event.status}</span>
        <span>r{event.revisionNumber}</span>
        {event.primaryDomain && <span>{event.primaryDomain}</span>}
      </p>
      <h3 className="entry__title">{event.headline}</h3>
      <p className="entry__line">{event.whatHappened}</p>
      <p className="note">限制：{event.evidenceLimitations}</p>
      {event.sources.length > 0 && (
        <p className="note">
          來源：
          {event.sources.map((src, i) => {
            const url = typeof src.url === "string" ? src.url : "";
            const title = typeof src.title === "string" ? src.title : url;
            return url ? (
              <span key={url}>
                {i > 0 ? "、" : ""}
                <a href={url} rel="noopener">
                  {title}
                </a>
              </span>
            ) : null;
          })}
        </p>
      )}
      {event.claims.length > 0 && (
        <details className="accordion">
          <summary>
            檢視 Claim-Evidence 對應（{event.claims.length} 條）
          </summary>
          <ul>
            {event.claims.map((claim, idx) => (
              <li key={idx}>
                <strong>{String(claim.claimText ?? "")}</strong>
                <p className="note">
                  摘錄：{String(claim.evidenceQuote ?? "")}
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}
      {message ? (
        <p className="callout" role="status">
          {message}
        </p>
      ) : (
        <div
          className="review-actions"
          role="group"
          aria-label="Newsroom 事件審核"
        >
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="審核備註或原因（選填）"
            aria-label="審核備註或原因"
          />
          {event.status !== "published" && (
            <button
              className="btn btn--primary"
              type="button"
              disabled={busy}
              onClick={() => act("approve")}
            >
              核准發布
            </button>
          )}
          {event.status !== "rejected" && event.status !== "published" && (
            <button
              className="btn btn--secondary"
              type="button"
              disabled={busy}
              onClick={() => act("reject")}
            >
              拒絕
            </button>
          )}
          {event.status === "published" && (
            <button
              className="btn btn--secondary"
              type="button"
              disabled={busy}
              onClick={() => act("withdraw")}
            >
              撤下
            </button>
          )}
        </div>
      )}
    </li>
  );
}

export function ReviewQueue({ items }: { items: Pending[] }) {
  const account = useAccount();
  const signedInAdmin =
    account.status === "signed-in" && account.isAdmin ? account : null;
  const [newsEvents, setNewsEvents] = useState<AdminNewsEvent[] | null>(null);

  useEffect(() => {
    if (!signedInAdmin) return;
    let live = true;
    apiFetch("/admin/news-events?limit=50", signedInAdmin.token)
      .then((res) => (res.ok ? res.json() : null))
      .then((body: { items?: AdminNewsEvent[] } | null) => {
        if (live) setNewsEvents(body?.items ?? []);
      })
      .catch(() => live && setNewsEvents([]));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signedInAdmin?.userId]);

  if (!authEnabled) return <p>登入功能尚未開放。</p>;
  if (account.status === "loading") return <p aria-live="polite">載入中…</p>;
  if (!signedInAdmin) return <p>只有管理者可以使用這一頁。</p>;
  return (
    <>
      <section className="page__section" aria-labelledby="legacy-review-title">
        <h2 id="legacy-review-title">AI 未審文獻與消息</h2>
        {items.length === 0 ? (
          <p>目前沒有待審的文獻或消息。</p>
        ) : (
          <>
            <p>共 {items.length} 則待審。</p>
            <ul className="entries">
              {items.map((item) => (
                <li className="entry" key={`${item.kind}:${item.target}`}>
                  <p className="eyebrow">
                    <span>{KIND[item.kind]}</span>
                    <span>{item.date}</span>
                  </p>
                  <h3 className="entry__title">
                    <Link href={item.href}>{item.title}</Link>
                  </h3>
                  <ReviewActions kind={item.kind} target={item.target} />
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
      <section
        className="page__section"
        aria-labelledby="newsroom-review-title"
      >
        <h2 id="newsroom-review-title">Newsroom 事件審核佇列</h2>
        {newsEvents === null ? (
          <p aria-live="polite">載入 Newsroom 事件中…</p>
        ) : newsEvents.length === 0 ? (
          <p>目前沒有待審或近期 Newsroom 事件。</p>
        ) : (
          <ul className="entries">
            {newsEvents.map((event) => (
              <NewsEventReviewCard
                event={event}
                token={signedInAdmin.token}
                key={event.id}
              />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
