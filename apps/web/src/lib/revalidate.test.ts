import { describe, expect, it, vi } from "vitest";
import { CONTENT_TAG } from "./content";
import { handleRevalidate, type RevalidateOps } from "./revalidate";

function req(body?: unknown, token?: string): Request {
  return new Request("http://site.test/api/revalidate", {
    method: "POST",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body:
      body === undefined
        ? undefined
        : typeof body === "string"
          ? body
          : JSON.stringify(body),
  });
}

function ops() {
  return {
    revalidateTag: vi.fn<RevalidateOps["revalidateTag"]>(),
    revalidatePath: vi.fn<RevalidateOps["revalidatePath"]>(),
  };
}

describe("POST /api/revalidate", () => {
  it("returns 503 when GUTHUB_REVALIDATE_SECRET is not configured", async () => {
    const mockOps = ops();
    const res = await handleRevalidate(req(undefined, "secret"), mockOps, "");
    expect(res.status).toBe(503);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(mockOps.revalidateTag).not.toHaveBeenCalled();
  });

  it("rejects missing or wrong Bearer tokens with 401", async () => {
    const mockOps = ops();
    expect((await handleRevalidate(req(), mockOps, "top-secret")).status).toBe(
      401,
    );
    expect(
      (await handleRevalidate(req(undefined, "wrong"), mockOps, "top-secret"))
        .status,
    ).toBe(401);
    expect(mockOps.revalidateTag).not.toHaveBeenCalled();
  });

  it("defaults to immediate expiration of the master content tag on empty body", async () => {
    const mockOps = ops();
    const res = await handleRevalidate(
      req(undefined, "top-secret"),
      mockOps,
      "top-secret",
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(await res.json()).toEqual({
      revalidated: true,
      tags: [CONTENT_TAG],
      paths: [],
    });
    expect(mockOps.revalidateTag).toHaveBeenCalledWith(CONTENT_TAG, {
      expire: 0,
    });
  });

  it("revalidates explicit allowed tags and paths and deduplicates entries", async () => {
    const mockOps = ops();
    const res = await handleRevalidate(
      req(
        {
          tags: ["papers", "paper:niche2", "papers"],
          paths: ["/", "/papers/niche2/"],
        },
        "top-secret",
      ),
      mockOps,
      "top-secret",
    );
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      revalidated: true,
      tags: ["papers", "paper:niche2"],
      paths: ["/", "/papers/niche2/"],
    });
    expect(mockOps.revalidateTag).toHaveBeenCalledTimes(2);
    expect(mockOps.revalidatePath).toHaveBeenCalledWith("/");
    expect(mockOps.revalidatePath).toHaveBeenCalledWith("/papers/niche2/");
  });

  it("rejects malformed JSON, unknown tags, and invalid paths with 400", async () => {
    const mockOps = ops();
    expect(
      (await handleRevalidate(req("{bad", "top-secret"), mockOps, "top-secret"))
        .status,
    ).toBe(400);
    expect(
      (
        await handleRevalidate(
          req({ tags: ["arbitrary-tag"] }, "top-secret"),
          mockOps,
          "top-secret",
        )
      ).status,
    ).toBe(400);
    expect(
      (
        await handleRevalidate(
          req({ paths: ["https://evil.example/"] }, "top-secret"),
          mockOps,
          "top-secret",
        )
      ).status,
    ).toBe(400);
    expect(mockOps.revalidateTag).not.toHaveBeenCalled();
    expect(mockOps.revalidatePath).not.toHaveBeenCalled();
  });
});
