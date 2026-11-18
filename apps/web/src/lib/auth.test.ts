import { afterEach, describe, expect, it, vi } from "vitest";
import { callbackError, displayNameError, returnPath, safeNext } from "./auth";

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
    // Browsers drop tabs and newlines while parsing URLs, turning these into //evil.test.
    ["/\t/evil.test/", "/"],
    ["/\n/evil.test/", "/"],
    ["/\r\\evil.test/", "/"],
    [" //evil.test/", "/"],
    // Dot segments that normalize into a protocol-relative path.
    ["/.//evil.test/", "/"],
    ["/a/..//evil.test/", "/"],
    ["/./\\evil.test/", "/"],
    ["/%2F%2Fevil.test/", "/%2F%2Fevil.test/"],
    ["/auth%2Fcallback/", "/auth%2Fcallback/"],
  ])("%j -> %s", (input, expected) => {
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

describe("returnPath", () => {
  it("adds the trailing slash site URLs use, once", () => {
    expect(returnPath("/papers/niche2")).toBe("/papers/niche2/");
    expect(returnPath("/papers/niche2/")).toBe("/papers/niche2/");
    expect(returnPath("/")).toBe("/");
  });
});

describe("callbackError explains a failed sign-in or Google link", () => {
  it.each([
    ["", "", null],
    ["?code=abc", "", null],
    [
      "?error=server_error&error_code=identity_already_exists&error_description=Identity+is+already+linked",
      "",
      "這個 Google 帳號已經是另一個 GutHub 帳號，不能再連結。請來信請我們刪除那個帳號後再連結一次。",
    ],
    [
      "",
      "#error=server_error&error_code=identity_already_exists",
      "這個 Google 帳號已經是另一個 GutHub 帳號，不能再連結。請來信請我們刪除那個帳號後再連結一次。",
    ],
    [
      "?error=bad&error_code=manual_linking_disabled",
      "",
      "目前還不能連結 Google 帳號，請稍後再試。",
    ],
    ["?error=access_denied", "", "你取消了 Google 授權，沒有做任何變更。"],
    ["?error=server_error", "", "沒有完成，請再試一次。"],
  ])("%s %s", (search, hash, expected) => {
    expect(callbackError(search, hash)).toBe(expected);
  });
});
