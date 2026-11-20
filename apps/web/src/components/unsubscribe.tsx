"use client";

import Link from "next/link";
import { useState } from "react";
import { unsubscribe } from "@/lib/paper-follows";

export function Unsubscribe({
  token,
  paperId,
  title,
}: {
  token: string | null;
  paperId: string | null;
  title: string | null;
}) {
  const [state, setState] = useState<
    "idle" | "busy" | "done" | "unknown" | "failed"
  >("idle");

  if (!token || state === "unknown")
    return (
      <p role="alert">
        這個連結無效或已失效。請登入後到
        <Link href="/account/">帳號設定</Link>管理追蹤與每日留言通知。
      </p>
    );
  if (state === "done")
    return (
      <p role="status">
        {paperId
          ? `已取消追蹤${title ? `「${title}」` : "這篇文獻"}，之後不會再收到它的留言通知。`
          : "已停止每日留言通知。追蹤的文獻保留不變，可以在帳號設定重新開啟。"}
      </p>
    );

  async function confirm() {
    setState("busy");
    setState(await unsubscribe(token as string, paperId));
  }

  return (
    <>
      <p>
        {paperId
          ? `取消追蹤${title ? `「${title}」` : "這篇文獻"}的新留言，其他追蹤的文獻照常通知。`
          : "停止每天寄送的留言彙整信。追蹤的文獻會保留，之後可以在帳號設定重新開啟。"}
      </p>
      <button
        className="btn btn--primary"
        type="button"
        disabled={state === "busy"}
        onClick={confirm}
      >
        {paperId ? "取消追蹤這篇" : "停止每日留言通知"}
      </button>
      {state === "failed" && <p role="alert">操作失敗，請稍後再試。</p>}
    </>
  );
}
