"use client";

// The admin's queue of AI-unreviewed papers and stories (E7 #188): every "AI 未審" item on one page, each with the
// same buttons as its own page. The list is public content; only an admin sees the buttons and the queue.
import Link from "next/link";
import { useAccount } from "@/components/account";
import { ReviewActions } from "@/components/review-actions";
import { authEnabled } from "@/lib/auth";
import type { Pending } from "@/lib/review";

const KIND = { paper: "文獻", news: "消息" } as const;

export function ReviewQueue({ items }: { items: Pending[] }) {
  const account = useAccount();
  if (!authEnabled) return <p>登入功能尚未開放。</p>;
  if (account.status === "loading") return <p aria-live="polite">載入中…</p>;
  if (account.status !== "signed-in" || !account.isAdmin)
    return <p>只有管理者可以使用這一頁。</p>;
  if (items.length === 0) return <p>目前沒有待審的內容。</p>;
  return (
    <>
      <p>共 {items.length} 則待審。</p>
      <ul className="entries">
        {items.map((item) => (
          <li className="entry" key={`${item.kind}:${item.target}`}>
            <p className="eyebrow">
              <span>{KIND[item.kind]}</span>
              <span>{item.date}</span>
            </p>
            <h2 className="entry__title">
              <Link href={item.href}>{item.title}</Link>
            </h2>
            <ReviewActions kind={item.kind} target={item.target} />
          </li>
        ))}
      </ul>
    </>
  );
}
