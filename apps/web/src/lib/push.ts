// Web Push for new stories (C5 #95). The browser subscribes with the site's VAPID public key and hands the
// subscription to the API; the announce-news job sends each new story once. Subscriptions name a browser, not a
// person: these calls carry no token and no cookies.
import { apiUrl } from "./auth";

export const pushKey = process.env.NEXT_PUBLIC_PUSH_PUBLIC_KEY ?? "";
/** Push is offered only when the build knows the public key and the API, like the current site without a key. */
export const pushEnabled = Boolean(
  pushKey && process.env.NEXT_PUBLIC_GUTHUB_API_URL,
);

export type PushState = "off" | "on" | "blocked" | "failed" | "paused" | "ios";

const MESSAGES: Record<PushState, string> = {
  off: "",
  on: "推播已開啟。有新消息時這台裝置會收到通知。",
  blocked:
    "瀏覽器目前封鎖了本站的通知。請到瀏覽器的網站設定把通知改成允許，再按一次。",
  failed: "沒有開啟成功，請稍後再試。",
  paused: "網站維護中，暫時無法開啟推播，請稍後再試。",
  ios: "iPhone 與 iPad 要先把本站加入主畫面，再從主畫面打開，才能開啟推播。",
};

export const pushMessage = (state: PushState) => MESSAGES[state];

/** The base64url VAPID key as the bytes PushManager.subscribe() expects. */
export function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const base64 = base64url
    .replace(/-/g, "+")
    .replace(/_/g, "/")
    .padEnd(Math.ceil(base64url.length / 4) * 4, "=");
  return Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
}

function call(method: "PUT" | "DELETE", body: object): Promise<Response> {
  return fetch(apiUrl("/push/subscription"), {
    method,
    credentials: "omit",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Sends only what the API stores: the endpoint and the two keys. */
export function savePush(subscription: PushSubscriptionJSON) {
  return call("PUT", {
    endpoint: subscription.endpoint,
    keys: subscription.keys,
  });
}

export function removePush(endpoint: string) {
  return call("DELETE", { endpoint });
}
