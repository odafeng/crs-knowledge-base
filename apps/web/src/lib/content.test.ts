import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  decodePaper,
  getNews,
  getPaperBySlug,
  listAll,
  REVALIDATE_SECONDS,
} from "./content";

const page = (items: unknown[], nextCursor: string | null) =>
  Response.json({ items, nextCursor });
const baseUrl = "http://api.test/api/v1/";

describe("server content reads", () => {
  it("follows cursors with ISR caching and the largest page size", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(page([1, 2], "next"))
      .mockResolvedValueOnce(page([3], null));
    await expect(
      listAll<number>("/news", { fetcher, baseUrl }),
    ).resolves.toEqual([1, 2, 3]);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "http://api.test/api/v1/news?limit=100",
      "http://api.test/api/v1/news?limit=100&cursor=next",
    ]);
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      next: { revalidate: REVALIDATE_SECONDS },
    });
  });

  it("resolves a paper by its slug, not its ID", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockImplementation(async () =>
        page(
          [{ id: "STELLAR303_Lancet_2025", slug: "stellar303-lancet-2025" }],
          null,
        ),
      );
    await expect(
      getPaperBySlug("stellar303-lancet-2025", { fetcher, baseUrl }),
    ).resolves.toMatchObject({
      id: "STELLAR303_Lancet_2025",
    });
    await expect(
      getPaperBySlug("STELLAR303_Lancet_2025", { fetcher, baseUrl }),
    ).resolves.toBeNull();
  });

  it("raises the contract error for failures", async () => {
    const down = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(
        {
          error: {
            code: "unavailable",
            message: "Database unavailable",
            requestId: "r",
          },
        },
        { status: 503 },
      ),
    );
    await expect(getNews("x", { fetcher: down, baseUrl })).rejects.toEqual(
      new ApiError(503, "Database unavailable", "unavailable"),
    );
  });

  it("treats only the contract's not_found as missing, so a wrong upstream cannot cache 404 pages", async () => {
    const contract404 = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(
        {
          error: {
            code: "not_found",
            message: "News not found",
            requestId: "r",
          },
        },
        { status: 404 },
      ),
    );
    await expect(
      getNews("gone", { fetcher: contract404, baseUrl }),
    ).resolves.toBeNull();
    // e.g. GUTHUB_API_URL pointing at another server, or a proxy's own 404 page
    const foreign404 = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        Response.json({ detail: "Not Found" }, { status: 404 }),
      );
    await expect(
      getNews("x", { fetcher: foreign404, baseUrl }),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses to guess the API location", async () => {
    vi.stubEnv("GUTHUB_API_URL", "");
    await expect(getNews("x")).rejects.toThrow("GUTHUB_API_URL is not set");
    vi.unstubAllEnvs();
  });

  it("decodes the escaped text fields once, as sitegen does", () => {
    const paper = {
      id: "fresco",
      regimen: "A &amp; B",
      journal: "JAMA",
      endpoint: "OS",
      result: "HR 0.65, p&lt;.001",
      bottomLine: "&lt;5% 差異",
      detailHtml: "<p>p&lt;.001</p>",
    } as unknown as Parameters<typeof decodePaper>[0];
    expect(decodePaper(paper)).toMatchObject({
      regimen: "A & B",
      result: "HR 0.65, p<.001",
      bottomLine: "<5% 差異",
      detailHtml: "<p>p&lt;.001</p>", // HTML stays HTML
    });
  });
});
