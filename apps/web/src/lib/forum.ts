// The colorectal surgeon forum (H7 #129, ADR-0022): the rules and wording shared by the forum components. The API
// decides who may read (verified members only, everyone else gets 404); these pages only explain the gate.
import type { components } from "./api.generated";

export type ThreadSummary = components["schemas"]["ForumThreadSummary"];
export type ThreadPage = components["schemas"]["ForumThreadPage"];
export type ThreadDetail = components["schemas"]["ForumThreadDetail"];
export type OpeningPost = components["schemas"]["ForumOpeningPost"];
export type Reply = components["schemas"]["ForumPost"];
export type PostReceipt = components["schemas"]["ForumPostReceipt"];
export type OwnPost =
  components["schemas"]["ForumOwnPostPage"]["items"][number];

export const BODY_MAX = 5000;
export const TITLE_MAX = 120;

const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;

/** Same rules as the API: 1-5000 characters, not blank, newlines and tabs the only control characters. */
export function bodyError(body: string): string | null {
  if (!body.trim()) return "請輸入內容";
  if (CONTROL.test(body)) return "內容不能包含控制字元";
  const length = [...body].length;
  if (length > BODY_MAX) return `內容最多 ${BODY_MAX} 個字，目前 ${length} 字`;
  return null;
}

export function titleError(title: string): string | null {
  const trimmed = title.trim();
  if (!trimmed) return "請輸入標題";
  if (/[\u0000-\u001f\u007f]/.test(trimmed)) return "標題不能包含控制字元";
  const length = [...trimmed].length;
  if (length > TITLE_MAX)
    return `標題最多 ${TITLE_MAX} 個字，目前 ${length} 字`;
  return null;
}

/** Shown before every post (ADR-0022): case discussion must not identify a patient. */
export const DEIDENTIFY =
  "請勿張貼可識別病人的資訊：姓名、病歷號、身分證字號、生日、確切就診或手術日期、照片與影像、罕見到可以對應到個人的細節。病例請改寫成年齡區間與必要的臨床資訊。";

export type Action =
  "load" | "post" | "reply" | "edit" | "delete" | "report" | "like";

const KEEP = "你寫的內容還在。";
const PAUSED = "網站維護中，暫停發文、編輯與檢舉，閱讀不受影響。";

/** What went wrong, in terms of what the member can do; `null` status means the request never got an answer. */
export function errorMessage(
  status: number | null,
  action: Action,
  retryAfter?: number | null,
): string {
  if (action === "load") return "暫時無法載入論壇，請稍後再試。";
  const writes = action === "post" || action === "reply" || action === "edit";
  const keep = writes ? KEEP : "";
  if (status === 503 && retryAfter) {
    if (action === "like") return "網站維護中，暫停按讚，請稍後再試。";
    return writes
      ? `${PAUSED}你寫的內容還在，請稍後再送出。`
      : `${PAUSED}請稍後再試。`;
  }
  if (action === "like") {
    switch (status) {
      case null:
        return "按讚失敗，請檢查網路後再試一次。";
      case 404:
        return "這篇貼文已不存在。";
      case 429:
        return "按讚太頻繁，請稍後再試。";
      default:
        return "暫時無法按讚，請稍後再試。";
    }
  }
  switch (status) {
    case null:
      return `送出失敗，請檢查網路後再試一次。${keep}`;
    case 401:
      return `登入已過期，請重新登入後再送出。${keep}`;
    case 403:
      if (action === "report") return "不能檢舉自己的貼文。";
      return `只有作者可以${action === "delete" ? "刪除" : "修改"}這篇貼文。`;
    case 404:
      if (action === "post") return `你目前無法在論壇發文。${keep}`;
      if (action === "reply") return `這個話題已不存在，無法回覆。${keep}`;
      return "這篇貼文已不存在。";
    case 409:
      return "你已經檢舉過這篇貼文。";
    case 422:
      return `內容不符合規定，請檢查後再送出。${keep}`;
    case 429:
      if (!retryAfter) return `發文太頻繁，請稍後再試。${keep}`;
      if (retryAfter > 3600)
        return `今天的發文已達上限，請 ${Math.ceil(retryAfter / 3600)} 小時後再試。${keep}`;
      return `發文太頻繁，請 ${Math.ceil(retryAfter / 60)} 分鐘後再試。${keep}`;
    default:
      return `暫時無法送出，請稍後再試。${keep}`;
  }
}

/** What a member sees right after posting: published posts are visible at once, a first post waits. */
export function receiptMessage(status: PostReceipt["status"]): string {
  return status === "pending"
    ? "已送出。你在論壇的第一篇貼文要等維護者審核後才會公開，在那之前只有你看得到。"
    : "已發布。";
}

export function threadPath(id: string): string {
  return `/forum/${id}/`;
}

export function authorName(post: {
  anonymous: boolean;
  displayName: string | null;
}): string {
  return post.anonymous ? "匿名醫師" : (post.displayName ?? "");
}

export function postDate(iso: string): string {
  return iso.slice(0, 10);
}

/** A paper ID from a `?paperId=` link, as the API accepts it, or null. */
export function paperIdParam(value: string | null): string | null {
  const id = value?.trim();
  return id && /^[A-Za-z0-9_-]{1,100}$/.test(id) ? id : null;
}
