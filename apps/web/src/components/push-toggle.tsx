"use client";

// The push button in the subscribe box (C5 #95), the Next.js version of static/scripts/push.js. Hidden until the page
// knows the browser can do push, as on the current site; the service worker is the one OfflineReading registers.
import { useEffect, useState, type ReactNode } from "react";
import { retryAfterOf } from "@/lib/comments";
import {
  keyBytes,
  pushKey,
  pushMessage,
  removePush,
  savePush,
  type PushState,
} from "@/lib/push";

const supported = () =>
  "serviceWorker" in navigator &&
  "PushManager" in window &&
  "Notification" in window;
const onIos = () =>
  /iPad|iPhone|iPod/.test(navigator.userAgent) &&
  !(navigator as Navigator & { standalone?: boolean }).standalone;

async function currentSubscription() {
  const registration = await navigator.serviceWorker.getRegistration("/");
  return (await registration?.pushManager.getSubscription()) ?? null;
}

async function turnOn(): Promise<PushState> {
  if ((await Notification.requestPermission()) !== "granted") return "blocked";
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: keyBytes(pushKey),
  });
  const response = await savePush(subscription.toJSON()).catch(() => null);
  if (response?.ok) return "on";
  // The API did not store it: drop it here too, so the button never claims a subscription nobody will use.
  await subscription.unsubscribe();
  return response?.status === 503 && retryAfterOf(response)
    ? "paused"
    : "failed";
}

async function turnOff(): Promise<PushState> {
  const subscription = await currentSubscription();
  if (subscription) {
    // Unsubscribing in the browser is what stops notifications; if the API call fails, the next send gets "gone"
    // from the push service and deletes the stored copy.
    await subscription.unsubscribe();
    await removePush(subscription.endpoint).catch(() => null);
  }
  return "off";
}

/** `icon` comes from the server-rendered subscribe box, so the icon set stays out of the browser bundle. */
export function PushToggle({ icon }: { icon: ReactNode }) {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supported()) {
      if (onIos()) queueMicrotask(() => setState("ios"));
      return;
    }
    currentSubscription()
      .then((subscription) =>
        setState(
          subscription
            ? "on"
            : Notification.permission === "denied"
              ? "blocked"
              : "off",
        ),
      )
      .catch(() => setState("off"));
  }, []);

  async function toggle() {
    setBusy(true);
    setState(
      await (state === "on" ? turnOff() : turnOn()).catch(
        () => "failed" as const,
      ),
    );
    setBusy(false);
  }

  return (
    <>
      {state && state !== "ios" && (
        <button
          className="btn btn--primary"
          type="button"
          aria-pressed={state === "on"}
          data-push-state={state}
          disabled={busy}
          onClick={toggle}
        >
          {icon}
          {state === "on" ? "關閉推播" : "開啟推播"}
        </button>
      )}
      <p className="alerts__status" role="status">
        {state ? pushMessage(state) : ""}
      </p>
    </>
  );
}
