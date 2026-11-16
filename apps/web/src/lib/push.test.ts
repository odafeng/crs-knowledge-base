import { afterEach, describe, expect, it, vi } from "vitest";
import { keyBytes, pushMessage, removePush, savePush } from "./push";

describe("keyBytes turns the base64url VAPID key into what subscribe() wants", () => {
  it("decodes without padding and with URL-safe characters", () => {
    expect([...keyBytes("_-8")]).toEqual([0xff, 0xef]);
    expect(keyBytes("B" + "A".repeat(86)).length).toBe(65);
  });
});

describe("pushMessage tells the reader what happened", () => {
  it.each([
    ["off", ""],
    ["on", "推播已開啟。有新消息時這台裝置會收到通知。"],
    [
      "blocked",
      "瀏覽器目前封鎖了本站的通知。請到瀏覽器的網站設定把通知改成允許，再按一次。",
    ],
    ["failed", "沒有開啟成功，請稍後再試。"],
    ["paused", "網站維護中，暫時無法開啟推播，請稍後再試。"],
    [
      "ios",
      "iPhone 與 iPad 要先把本站加入主畫面，再從主畫面打開，才能開啟推播。",
    ],
  ] as const)("%s", (state, message) => {
    expect(pushMessage(state)).toBe(message);
  });
});

describe("the API calls carry only the subscription, never credentials", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("stores and removes by endpoint", async () => {
    vi.stubEnv("NEXT_PUBLIC_GUTHUB_API_URL", "https://api.test/api/v1");
    const calls: [string, RequestInit][] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
      calls.push([url, init]);
      return new Response(null, { status: 204 });
    });
    const subscription = {
      endpoint: "https://fcm.googleapis.com/fcm/send/abc",
      expirationTime: null,
      keys: { p256dh: "p", auth: "a" },
    };
    await savePush(subscription);
    await removePush(subscription.endpoint);
    expect(calls.map(([url, init]) => [url, init.method, init.body])).toEqual([
      [
        "https://api.test/api/v1/push/subscription",
        "PUT",
        JSON.stringify({
          endpoint: subscription.endpoint,
          keys: subscription.keys,
        }),
      ],
      [
        "https://api.test/api/v1/push/subscription",
        "DELETE",
        JSON.stringify({ endpoint: subscription.endpoint }),
      ],
    ]);
    expect(calls.every(([, init]) => init.credentials === "omit")).toBe(true);
  });
});
