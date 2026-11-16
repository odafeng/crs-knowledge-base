"use client";

// Registers /sw.js for every reader, as offline.js does on the current site, then asks it to sync the
// offline copy with the public index (it skips the work if it synced in the last ten minutes).
import { useEffect } from "react";

export function OfflineReading() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker
      .register("/sw.js")
      .then(() => navigator.serviceWorker.ready)
      .then((registration) =>
        registration.active?.postMessage({ type: "sync" }),
      )
      .catch(console.error);
  }, []);
  return null;
}
