// What an admin sees after pressing a review or unpublish button (E6 #159). The API only records the request; the
// content-requests job applies it about a minute later, and pages follow within the 5-minute ISR window.
import {
  headline,
  isUnreviewed,
  newsPath,
  paperPath,
  paperTitle,
  publishedAt,
  type News,
  type Paper,
} from "./site";

export type ReviewAction = "review" | "unpublish";

export function reviewMessage(
  action: ReviewAction,
  status: number | null,
  started: boolean,
  retryAfter: string | null = null,
): { ok: boolean; message: string } {
  if (status === 202) {
    if (!started)
      return {
        ok: true,
        message: "已記下，但背景工作暫時無法啟動，會在下次執行時處理。",
      };
    return {
      ok: true,
      message:
        action === "review"
          ? "已送出，約一分鐘後標為已審；頁面最多 5 分鐘後更新。"
          : "已送出撤下，約一分鐘後生效；頁面最多 5 分鐘後消失。",
    };
  }
  switch (status) {
    case null:
      return { ok: false, message: "送出失敗，請檢查網路後再試一次。" };
    case 401:
      return { ok: false, message: "登入已過期，請重新登入後再試。" };
    case 403:
      return { ok: false, message: "需要管理者權限。" };
    case 503:
      return {
        ok: false,
        message: retryAfter
          ? "網站維護中，暫停審閱與撤下，請稍後再試。"
          : "暫時無法送出，請稍後再試。",
      };
    default:
      return { ok: false, message: "暫時無法送出，請稍後再試。" };
  }
}

/** One AI-unreviewed paper or story in the admin's review queue (E7 #188). */
export type Pending = {
  kind: "paper" | "news";
  target: string;
  title: string;
  href: string;
  date: string;
};

/** Everything still marked "AI 未審", newest first, papers and stories together. */
export function pendingReview(
  papers: readonly Paper[],
  news: readonly News[],
): Pending[] {
  const items: Pending[] = [
    ...papers.filter(isUnreviewed).map((paper) => ({
      kind: "paper" as const,
      target: paper.id,
      title: paperTitle(paper),
      href: paperPath(paper),
      date: publishedAt(paper),
    })),
    ...news.filter(isUnreviewed).map((item) => ({
      kind: "news" as const,
      target: item.id,
      title: headline(item),
      href: newsPath(item),
      date: item.publishedAt,
    })),
  ];
  return items.sort((a, b) => b.date.localeCompare(a.date));
}
