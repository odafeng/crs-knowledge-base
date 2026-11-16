import { describe, expect, it, vi } from "vitest";
import { ApiError, getPaper, type Paper } from "./api";

const paper: Paper = {
  id: "beacon-2019",
  slug: "beacon-2019",
  topic: "mCRC-BRAF-V600E",
  year: 2019,
  journal: "NEJM",
  studyType: "Phase 3 RCT",
  regimen: "EC ± binimetinib vs cetux+chemo",
  endpoint: "OS (co-primary)",
  result: "mOS 9.0 vs 5.4 mo, HR 0.52",
  bottomLine: "首次證實 BRAF+EGFR 雙阻斷在 2L+ BRAF V600E mCRC 的 OS 獲益",
  relations: [],
  source: "curated",
  reviewedAt: "2026-06-07",
  detailHtml: "",
};

describe("content API client", () => {
  it("reads the shared Paper contract without using a shared cache", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(paper));
    await expect(getPaper(paper.id, { fetcher })).resolves.toEqual(paper);
    expect(fetcher).toHaveBeenCalledWith("/api/v1/papers/beacon-2019", {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
  });

  it("encodes IDs and supports an explicitly configured API origin", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(paper));
    await getPaper("id/with?query", {
      fetcher,
      baseUrl: "https://api.example.test/api/v1/",
    });
    expect(fetcher.mock.calls[0][0]).toBe(
      "https://api.example.test/api/v1/papers/id%2Fwith%3Fquery",
    );
  });

  it("preserves a structured API failure for the UI", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(
        {
          error: {
            code: "not_found",
            message: "找不到文獻",
            requestId: "test-request",
          },
        },
        { status: 404 },
      ),
    );
    await expect(getPaper("missing", { fetcher })).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      code: "not_found",
      message: "找不到文獻",
    });
  });

  it("handles non-JSON failures without displaying a server's HTML", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response("<h1>proxy unavailable</h1>", { status: 503 }),
      );
    const failure = getPaper("id", { fetcher });
    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await expect(failure).rejects.toMatchObject({
      status: 503,
      message: "無法載入文獻，請稍後再試。",
    });
  });

  it("lets the caller recover from a network failure", async () => {
    const failure = new TypeError("network unavailable");
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(failure);
    await expect(getPaper("id", { fetcher })).rejects.toBe(failure);
  });
});
