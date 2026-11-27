import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  CONTENT_TAG,
  CONTENT_TAGS,
  getDomain,
  getNews,
  getPaperBySlug,
  listAll,
  listDomains,
  listPapers,
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
      next: { revalidate: REVALIDATE_SECONDS, tags: [CONTENT_TAG] },
    });
  });

  it("requests slim paper lists without detailHtml and tags caches for on-demand revalidation", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(
      page(
        [
          {
            id: "kn177",
            slug: "kn177",
            regimen: "A & B",
            detailHtml: "",
          },
        ],
        null,
      ),
    );
    await expect(listPapers({ fetcher, baseUrl })).resolves.toMatchObject([
      { id: "kn177", regimen: "A & B", detailHtml: "" },
    ]);
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api.test/api/v1/papers?limit=100&includeDetail=false",
    );
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      next: {
        revalidate: REVALIDATE_SECONDS,
        tags: [CONTENT_TAG, CONTENT_TAGS.papers],
      },
    });
  });

  it("resolves a paper directly via /papers/by-slug/{slug} and rejects non-slug IDs", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(
      Response.json({
        id: "STELLAR303_Lancet_2025",
        slug: "stellar303-lancet-2025",
        regimen: "A & B",
        detailHtml: "<p>full</p>",
      }),
    );
    await expect(
      getPaperBySlug("stellar303-lancet-2025", { fetcher, baseUrl }),
    ).resolves.toMatchObject({
      id: "STELLAR303_Lancet_2025",
      regimen: "A & B",
      detailHtml: "<p>full</p>",
    });
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api.test/api/v1/papers/by-slug/stellar303-lancet-2025",
    );
    // Uppercase / underscore IDs are never valid slugs and return null without fetching.
    await expect(
      getPaperBySlug("STELLAR303_Lancet_2025", { fetcher, baseUrl }),
    ).resolves.toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("returns null on endpoint 404 and falls back to /papers if an older API lacks the route", async () => {
    const missingPaper = vi.fn<typeof fetch>().mockResolvedValueOnce(
      Response.json(
        {
          error: {
            code: "not_found",
            message: "Paper not found",
            requestId: "r",
          },
        },
        { status: 404 },
      ),
    );
    await expect(
      getPaperBySlug("missing-slug", { fetcher: missingPaper, baseUrl }),
    ).resolves.toBeNull();
    expect(missingPaper).toHaveBeenCalledTimes(1);

    const legacyApi = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json(
          {
            error: {
              code: "not_found",
              message: "Not Found",
              requestId: "r",
            },
          },
          { status: 404 },
        ),
      )
      .mockResolvedValueOnce(
        page(
          [
            {
              id: "STELLAR303_Lancet_2025",
              slug: "stellar303-lancet-2025",
              detailHtml: "<p>legacy</p>",
            },
          ],
          null,
        ),
      );
    await expect(
      getPaperBySlug("stellar303-lancet-2025", { fetcher: legacyApi, baseUrl }),
    ).resolves.toMatchObject({
      id: "STELLAR303_Lancet_2025",
      detailHtml: "<p>legacy</p>",
    });
    expect(legacyApi.mock.calls[1][0]).toBe(
      "http://api.test/api/v1/papers?limit=100",
    );
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

  it("reads specialty domains from the API and falls back to the bundled registry on older APIs", async () => {
    const legacyApi = vi.fn<typeof fetch>().mockResolvedValue(
      Response.json(
        {
          error: { code: "not_found", message: "Not Found", requestId: "r" },
        },
        { status: 404 },
      ),
    );
    const domains = await listDomains({ fetcher: legacyApi, baseUrl });
    expect(domains).toHaveLength(8);
    expect(domains[0].slug).toBe("colorectal-oncology");
    const single = await getDomain("endoscopy", {
      fetcher: legacyApi,
      baseUrl,
    });
    expect(single?.labelZh).toBe("內視鏡");
    await expect(
      getDomain("not-a-domain", { fetcher: legacyApi, baseUrl }),
    ).resolves.toBeNull();
  });
});
