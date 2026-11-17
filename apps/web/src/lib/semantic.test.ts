import { afterEach, describe, expect, it, vi } from "vitest";
import { outcomeOf, semanticSearch } from "./semantic";

const hit = {
  kind: "paper" as const,
  path: "/papers/correct/",
  title: "Regorafenib",
  snippet: "s",
  score: 0.56,
};

describe("semantic search", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts the trimmed question without a session and returns the hits", async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      Response.json({ results: [hit] }),
    );
    vi.stubGlobal("fetch", fetcher);
    await expect(semanticSearch("  regorafenib 先用嗎 ")).resolves.toEqual({
      kind: "done",
      hits: [hit],
    });
    const [url, init] = fetcher.mock.calls[0];
    expect(String(url)).toMatch(/\/semantic-search$/);
    expect(init).toMatchObject({ method: "POST", credentials: "omit" });
    expect(JSON.parse(String(init?.body))).toEqual({
      query: "regorafenib 先用嗎",
    });
    expect(init?.headers).not.toHaveProperty("Authorization");
  });

  it("explains failures in words a reader can act on", async () => {
    expect(outcomeOf(503)).toMatchObject({
      message: expect.stringContaining("關鍵字搜尋"),
    });
    expect(outcomeOf(422)).toMatchObject({
      message: expect.stringContaining("2 到 200"),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("offline"))),
    );
    await expect(semanticSearch("x y")).resolves.toMatchObject({
      kind: "error",
      message: expect.stringContaining("網路"),
    });
  });
});
