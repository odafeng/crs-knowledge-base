// Reader comments on paper pages (D3 #69): the rules and wording shared by the comment components.
import type { components } from "./api.generated";

export type PublicComment = components["schemas"]["PublicComment"];
export type OwnedComment = components["schemas"]["OwnedComment"];
export type CommentPage = components["schemas"]["PublicCommentPage"];
export type OwnedCommentPage = components["schemas"]["OwnedCommentPage"];
export type CommentReceipt = components["schemas"]["CommentReceipt"];

export const BODY_MAX = 2000;

/** Same rules as the API (1-2000 characters, not blank, newlines and tabs the only control characters). */
export function bodyError(body: string): string | null {
  if (!body.trim()) return "請輸入留言內容";
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(body))
    return "留言不能包含控制字元";
  const length = [...body].length;
  if (length > BODY_MAX) return `留言最多 ${BODY_MAX} 個字，目前 ${length} 字`;
  return null;
}

export type Action = "load" | "post" | "edit" | "delete" | "report";

const KEEP = "你寫的內容還在。";

/**
 * What went wrong, in terms of what the reader can do; `null` status means the request never got an answer.
 * `retryAfter` is the API's Retry-After (seconds) on 429.
 */
export function errorMessage(
  status: number | null,
  action: Action,
  retryAfter?: number | null,
): string {
  if (action === "load") return "暫時無法載入留言，請稍後再試。";
  const keep = action === "post" || action === "edit" ? KEEP : "";
  switch (status) {
    case null:
      return `送出失敗，請檢查網路後再試一次。${keep}`;
    case 401:
      return `登入已過期，請重新登入後再送出。${keep}`;
    case 403:
      if (action === "post" || action === "report")
        return "請先設定顯示名稱再留言。";
      return `只有作者可以${action === "edit" ? "修改" : "刪除"}這則留言。`;
    case 404:
      return action === "post"
        ? "這篇文獻已撤下，無法留言。"
        : "這則留言已不存在。";
    case 409:
      return "你已經檢舉過這則留言。";
    case 422:
      return `內容不符合規定，請檢查後再送出。${keep}`;
    case 429:
      if (!retryAfter) return `留言太頻繁，請稍後再試。${keep}`;
      if (retryAfter > 3600)
        return `今天的留言已達上限，請 ${Math.ceil(retryAfter / 3600)} 小時後再試。${keep}`;
      return `留言太頻繁，請 ${Math.ceil(retryAfter / 60)} 分鐘後再試。${keep}`;
    default:
      return `暫時無法送出，請稍後再試。${keep}`;
  }
}

/**
 * The reader's own comments on this paper, from the private /me/comments: which public ones are theirs (to offer
 * edit and delete), and the ones only they can see (waiting for moderation or hidden).
 */
export function ownComments(items: OwnedComment[], paperId: string) {
  const here = items.filter((item) => item.comment.paperId === paperId);
  return {
    ids: new Set(here.map((item) => item.comment.id)),
    unpublished: here.filter((item) => item.status !== "published"),
  };
}

export function commentDate(iso: string): string {
  return iso.slice(0, 10);
}
