import { describe, expect, it } from "vitest";
import {
  BODY_MAX,
  authorName,
  bodyError,
  errorMessage,
  paperIdParam,
  receiptMessage,
  threadPath,
  titleError,
} from "./forum";

describe("forum input rules mirror the API", () => {
  it("accepts plain text up to the limit and explains what is wrong", () => {
    expect(
      bodyError("Five years of MRI follow-up.\n\tThen yearly."),
    ).toBeNull();
    expect(bodyError("   ")).toBe("請輸入內容");
    expect(bodyError("bell\u0007")).toBe("內容不能包含控制字元");
    expect(bodyError("字".repeat(BODY_MAX))).toBeNull();
    expect(bodyError("字".repeat(BODY_MAX + 1))).toBe(
      `內容最多 ${BODY_MAX} 個字，目前 ${BODY_MAX + 1} 字`,
    );
  });

  it("counts characters, not UTF-16 units", () => {
    expect(bodyError("😀".repeat(BODY_MAX))).toBeNull();
  });

  it("checks titles after trimming, with no line breaks", () => {
    expect(titleError("  TNT 後的 watch and wait  ")).toBeNull();
    expect(titleError(" ")).toBe("請輸入標題");
    expect(titleError("one\ntwo")).toBe("標題不能包含控制字元");
    expect(titleError("字".repeat(121))).toBe("標題最多 120 個字，目前 121 字");
  });
});

describe("forum messages", () => {
  it("keeps the text on failed writes and says how long to wait", () => {
    expect(errorMessage(null, "post")).toBe(
      "送出失敗，請檢查網路後再試一次。你寫的內容還在。",
    );
    expect(errorMessage(429, "reply", 600)).toBe(
      "發文太頻繁，請 10 分鐘後再試。你寫的內容還在。",
    );
    expect(errorMessage(429, "post", 7200)).toBe(
      "今天的發文已達上限，請 2 小時後再試。你寫的內容還在。",
    );
    expect(errorMessage(503, "edit", 600)).toBe(
      "網站維護中，暫停發文、編輯與檢舉，閱讀不受影響。你寫的內容還在，請稍後再送出。",
    );
  });

  it("names the action that failed", () => {
    expect(errorMessage(404, "reply")).toBe(
      "這個話題已不存在，無法回覆。你寫的內容還在。",
    );
    expect(errorMessage(409, "report")).toBe("你已經檢舉過這篇貼文。");
    expect(errorMessage(403, "delete")).toBe("只有作者可以刪除這篇貼文。");
    expect(errorMessage(429, "like")).toBe("按讚太頻繁，請稍後再試。");
    expect(errorMessage(500, "load")).toBe("暫時無法載入論壇，請稍後再試。");
  });

  it("tells a first-time poster about moderation", () => {
    expect(receiptMessage("pending")).toContain("要等維護者審核");
    expect(receiptMessage("published")).toBe("已發布。");
  });
});

describe("forum helpers", () => {
  it("never shows a name for anonymous posts", () => {
    expect(authorName({ anonymous: true, displayName: null })).toBe("匿名醫師");
    expect(authorName({ anonymous: false, displayName: "王醫師" })).toBe(
      "王醫師",
    );
  });

  it("builds thread paths and accepts only plausible paper IDs", () => {
    expect(threadPath("1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed")).toBe(
      "/forum/1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed/",
    );
    expect(paperIdParam(" niche2 ")).toBe("niche2");
    expect(paperIdParam("../admin")).toBeNull();
    expect(paperIdParam(null)).toBeNull();
  });
});
