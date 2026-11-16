import { describe, expect, it } from "vitest";
import {
  BODY_MAX,
  bodyError,
  errorMessage,
  retryAfterOf,
  ownComments,
  paperPathFromId,
  type OwnedComment,
  type PublicComment,
} from "./comments";

const comment = (id: string, paperId = "niche2"): PublicComment => ({
  id,
  paperId,
  body: `body ${id}`,
  anonymous: false,
  displayName: "Reader",
  createdAt: "2026-11-16T10:00:00Z",
  updatedAt: "2026-11-16T10:00:00Z",
  likeCount: 0,
});
const owned = (
  id: string,
  status: OwnedComment["status"],
  paperId = "niche2",
) => ({
  comment: comment(id, paperId),
  status,
});

describe("comment bodies follow the API rules", () => {
  it("accepts text with newlines up to the limit", () => {
    expect(bodyError("第一行\n第二行")).toBeNull();
    expect(bodyError("x".repeat(BODY_MAX))).toBeNull();
  });

  it.each([
    ["", "請輸入留言內容"],
    [" \n\t ", "請輸入留言內容"],
    ["x".repeat(BODY_MAX + 1), "留言最多 2000 個字，目前 2001 字"],
    ["bell\u0007", "留言不能包含控制字元"],
  ])("rejects %j", (body, message) => {
    expect(bodyError(body)).toBe(message);
  });

  it("counts characters the way the API does (code points, not UTF-16 units)", () => {
    expect(bodyError("😀".repeat(BODY_MAX))).toBeNull();
  });
});

describe("error messages tell the reader what to do next", () => {
  it.each([
    [null, "post", "送出失敗，請檢查網路後再試一次。你寫的內容還在。"],
    [401, "post", "登入已過期，請重新登入後再送出。你寫的內容還在。"],
    [403, "post", "請先設定顯示名稱再留言。"],
    [404, "post", "這篇文獻已撤下，無法留言。"],
    [429, "post", "留言太頻繁，請稍後再試。你寫的內容還在。"],
    [503, "load", "暫時無法載入留言，請稍後再試。"],
    [409, "report", "你已經檢舉過這則留言。"],
    [404, "edit", "這則留言已不存在。"],
    [403, "delete", "只有作者可以刪除這則留言。"],
  ] as const)("%s on %s", (status, action, message) => {
    expect(errorMessage(status, action)).toBe(message);
  });
});

describe("likes", () => {
  it.each([
    [null, "按讚失敗，請檢查網路後再試一次。"],
    [403, "請先設定顯示名稱再按讚。"],
    [404, "這則留言已不存在。"],
    [429, "按讚太頻繁，請稍後再試。"],
    [503, "暫時無法按讚，請稍後再試。"],
  ] as const)("%s", (status, message) => {
    expect(errorMessage(status, "like")).toBe(message);
  });
});

describe("maintenance (503 with Retry-After) is told apart from an outage", () => {
  it.each([
    [
      "post",
      "網站維護中，暫停留言、編輯與檢舉，閱讀不受影響。你寫的內容還在，請稍後再送出。",
    ],
    [
      "edit",
      "網站維護中，暫停留言、編輯與檢舉，閱讀不受影響。你寫的內容還在，請稍後再送出。",
    ],
    ["delete", "網站維護中，暫停留言、編輯與檢舉，閱讀不受影響。請稍後再試。"],
    ["report", "網站維護中，暫停留言、編輯與檢舉，閱讀不受影響。請稍後再試。"],
    ["like", "網站維護中，暫停按讚，請稍後再試。"],
  ] as const)("%s", (action, message) => {
    expect(errorMessage(503, action, 600)).toBe(message);
  });

  it("keeps the outage wording without Retry-After", () => {
    expect(errorMessage(503, "post")).toBe(
      "暫時無法送出，請稍後再試。你寫的內容還在。",
    );
  });

  it("reads Retry-After from a response, if any", () => {
    const headers = (value: string | null) =>
      ({
        headers: new Headers(value ? { "Retry-After": value } : {}),
      }) as Response;
    expect(retryAfterOf(headers("600"))).toBe(600);
    expect(retryAfterOf(headers(null))).toBeNull();
    expect(retryAfterOf(null)).toBeNull();
  });
});

describe("rate limits say how long to wait", () => {
  it.each([
    [45, "留言太頻繁，請 1 分鐘後再試。你寫的內容還在。"],
    [540, "留言太頻繁，請 9 分鐘後再試。你寫的內容還在。"],
    [7200, "今天的留言已達上限，請 2 小時後再試。你寫的內容還在。"],
  ])("Retry-After %i", (seconds, message) => {
    expect(errorMessage(429, "post", seconds)).toBe(message);
  });
});

describe("ownComments marks the reader's comments without any author field", () => {
  it("finds own public comments and lists unpublished ones for this paper only", () => {
    const mine = ownComments(
      [
        owned("a", "published"),
        owned("b", "pending"),
        owned("c", "hidden"),
        owned("d", "pending", "other-paper"),
      ],
      "niche2",
    );
    expect([...mine.ids].sort()).toEqual(["a", "b", "c"]);
    expect(mine.unpublished.map((o) => [o.comment.id, o.status])).toEqual([
      ["b", "pending"],
      ["c", "hidden"],
    ]);
  });
});

describe("paperPathFromId", () => {
  it("follows the importer's slug rule", () => {
    expect(paperPathFromId("BEACON_2019")).toBe("/papers/beacon-2019/");
    expect(paperPathFromId("niche2")).toBe("/papers/niche2/");
  });
});
