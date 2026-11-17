import { describe, expect, it } from "vitest";
import { reviewMessage } from "./review";

describe("reviewMessage", () => {
  it("says when the change will show", () => {
    expect(reviewMessage("review", 202, true)).toEqual({
      ok: true,
      message: "已送出，約一分鐘後標為已審；頁面最多 5 分鐘後更新。",
    });
    expect(reviewMessage("unpublish", 202, true).message).toContain("撤下");
  });

  it("is honest when the job could not be started", () => {
    expect(reviewMessage("review", 202, false).message).toContain(
      "下次執行時處理",
    );
  });

  it("explains failures", () => {
    expect(reviewMessage("review", null, false).ok).toBe(false);
    expect(reviewMessage("review", 403, false).message).toBe(
      "需要管理者權限。",
    );
    expect(reviewMessage("review", 401, false).message).toContain("重新登入");
    expect(reviewMessage("review", 503, false, "600").message).toContain(
      "維護中",
    );
    expect(reviewMessage("review", 503, false).message).not.toContain("維護中");
  });
});
