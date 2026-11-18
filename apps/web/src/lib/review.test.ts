import { describe, expect, it } from "vitest";
import { pendingReview, reviewMessage } from "./review";
import type { News, Paper } from "./site";

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

describe("pendingReview lists what still carries the AI 未審 chip", () => {
  const paper = (id: string, status: string, date: string) =>
    ({
      id,
      slug: id.toLowerCase(),
      regimen: `Regimen ${id}`,
      journal: "NEJM",
      year: 2026,
      addedAt: date,
      reviewedAt: date,
      review: { status },
    }) as unknown as Paper;
  const story = (id: string, status: string, publishedAt: string) =>
    ({
      id,
      publishedAt,
      headline: ["Head ", id],
      review: { status },
    }) as unknown as News;

  it("keeps only auto-published items, newest first, papers and stories mixed", () => {
    const items = pendingReview(
      [
        paper("A", "auto", "2026-11-10"),
        paper("B", "accepted", "2026-11-17"),
        paper("C", "auto", "2026-11-16"),
      ],
      [
        story("n1", "auto", "2026-11-12"),
        story("n2", "accepted", "2026-11-18"),
      ],
    );
    expect(items).toEqual([
      {
        kind: "paper",
        target: "C",
        title: "Regimen C（NEJM 2026）",
        href: "/papers/c/",
        date: "2026-11-16",
      },
      {
        kind: "news",
        target: "n1",
        title: "Head n1",
        href: "/news/n1/",
        date: "2026-11-12",
      },
      {
        kind: "paper",
        target: "A",
        title: "Regimen A（NEJM 2026）",
        href: "/papers/a/",
        date: "2026-11-10",
      },
    ]);
  });

  it("is empty when everything was reviewed", () => {
    expect(pendingReview([paper("B", "accepted", "2026-11-17")], [])).toEqual(
      [],
    );
  });
});
