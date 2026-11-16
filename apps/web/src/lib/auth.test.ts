import { afterEach, describe, expect, it, vi } from "vitest";
import { displayNameError, safeNext } from "./auth";

describe("safeNext keeps post-login redirects on this site", () => {
  it.each([
    ["/papers/niche2/", "/papers/niche2/"],
    ["/updates/?q=niche#q", "/updates/?q=niche#q"],
    [null, "/"],
    ["", "/"],
    ["papers/", "/"],
    ["//evil.test/", "/"],
    ["/\\evil.test", "/"],
    ["https://evil.test/", "/"],
    ["javascript:alert(1)", "/"],
    ["/auth/confirm/?token_hash=x", "/"],
    ["/login/", "/"],
  ])("%s -> %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });
});

describe("display names follow the API rules (1-80 characters after trimming)", () => {
  it("accepts ordinary names, including CJK", () => {
    expect(displayNameError("大腸外科 R1")).toBeNull();
    expect(displayNameError(" Dr. R ")).toBeNull();
    expect(displayNameError("x".repeat(80))).toBeNull();
  });

  it.each([
    ["", "請填寫顯示名稱"],
    ["   ", "請填寫顯示名稱"],
    ["x".repeat(81), "顯示名稱最多 80 個字"],
    ["line\nbreak", "顯示名稱不能包含換行或控制字元"],
  ])("rejects %j", (name, message) => {
    expect(displayNameError(name)).toBe(message);
  });
});

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("sends the access token as a bearer header, never cookies", async () => {
    vi.stubEnv("NEXT_PUBLIC_GUTHUB_API_URL", "https://api.test/api/v1/");
    const fetch = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetch);
    const { apiFetch } = await import("./auth");
    await apiFetch("/me", "token-123", { method: "PUT", body: "{}" });
    expect(fetch).toHaveBeenCalledWith("https://api.test/api/v1/me", {
      method: "PUT",
      body: "{}",
      credentials: "omit",
      cache: "no-store",
      headers: {
        Authorization: "Bearer token-123",
        "Content-Type": "application/json",
      },
    });
  });
});
