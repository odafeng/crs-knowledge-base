import { afterEach, describe, expect, it, vi } from "vitest";
import { followedPapers, unsubscribe } from "./paper-follows";

const paper = (id: string) => ({
  id,
  title: `${id} 標題`,
  path: `/papers/${id}/`,
});

describe("paper follows", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists followed papers in the API's order and drops ones no longer public", () => {
    const papers = [paper("a"), paper("b"), paper("c")];
    expect(followedPapers(["c", "gone", "a"], papers).map((p) => p.id)).toEqual(
      ["c", "a"],
    );
    expect(followedPapers([], papers)).toEqual([]);
  });

  it("unsubscribes with the link's token, and says when the link is not valid", async () => {
    const calls: string[] = [];
    const answer = (status: number) =>
      vi.fn(async (url: string, init: RequestInit) => {
        calls.push(`${init.method} ${url}`);
        return new Response(null, { status });
      });
    vi.stubGlobal("fetch", answer(204));
    expect(await unsubscribe("t-1", "keynote")).toBe("done");
    expect(calls.at(-1)).toBe(
      "POST /digest/unsubscribe?token=t-1&paper=keynote",
    );
    expect(await unsubscribe("t-1", null)).toBe("done");
    expect(calls.at(-1)).toBe("POST /digest/unsubscribe?token=t-1");
    vi.stubGlobal("fetch", answer(404));
    expect(await unsubscribe("t-1", null)).toBe("unknown");
    vi.stubGlobal("fetch", answer(503));
    expect(await unsubscribe("t-1", null)).toBe("failed");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new Error("offline"))),
    );
    expect(await unsubscribe("t-1", null)).toBe("failed");
  });
});
