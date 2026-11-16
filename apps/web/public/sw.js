// GutHub service worker (C3 #65): lets readers open public pages and search offline.
// Only public, shareable responses are stored. Requests that can carry a person's data (API, auth, account,
// admin, anything with an Authorization header) are never touched, and neither is a response marked private
// or no-store, so signing out or switching accounts cannot surface the previous reader's data from here.
const CACHE = "guthub-public-v1";
const SHELL = [
  "/",
  "/updates/",
  "/news/",
  "/topics/",
  "/mcrc/",
  "/robotic/",
  "/about/",
  "/subscribe/",
];
const INDEX = "/search.json";
const PRIVATE_PATH = /^\/(api|auth|me|account|admin)(\/|$)/;
const WITHDRAWABLE = /^\/(papers|news)\/[^/]+\/$/;
const ASSET = /\/_next\/static\/[^"'\s)\\]+/g;
const CSS_URL = /url\(\s*["']?([^"')]+)["']?\s*\)/g;
const SYNC_INTERVAL_MS = 10 * 60 * 1000;
let lastSync = 0;

function handles(request) {
  if (request.method !== "GET") return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || PRIVATE_PATH.test(url.pathname))
    return false;
  if (request.headers.has("Authorization")) return false;
  // React Server Component payloads vary by request header; Next.js falls back to a full page load when they fail.
  return !request.headers.has("RSC") && !url.searchParams.has("_rsc");
}

function storable(response) {
  return (
    response.ok &&
    !response.redirected &&
    !/private|no-store/i.test(response.headers.get("Cache-Control") || "")
  );
}

// Pages are stored by path, so ?utm=… and the like reuse the same copy.
const keyOf = (request) =>
  new URL(new URL(request.url).pathname, self.location.origin).href;

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  const key = keyOf(request);
  let response;
  try {
    response = await fetch(request);
  } catch {
    return (await cache.match(key)) || Response.error();
  }
  if (storable(response)) await cache.put(key, response.clone());
  else if (response.status === 404 || response.status === 410)
    await cache.delete(key);
  return response;
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (storable(response)) await cache.put(request, response.clone());
  return response;
}

/** Stores a page and the hashed Next.js assets it references, so it renders styled when opened offline. */
async function store(cache, path) {
  try {
    const response = await fetch(path);
    if (!storable(response)) return;
    if ((response.headers.get("Content-Type") || "").includes("text/html")) {
      const assets = new Set((await response.clone().text()).match(ASSET));
      for (const asset of assets) {
        if (await cache.match(asset)) continue;
        const assetResponse = await fetch(asset);
        if (storable(assetResponse)) await cache.put(asset, assetResponse);
      }
    }
    await cache.put(new URL(path, self.location.origin).href, response);
  } catch {
    // Offline or a server error: keep whatever copy is already stored.
  }
}

/**
 * Each deploy brings new hashed assets. Keep only those a stored page or stylesheet still references,
 * so older pages stay styled offline while assets nothing points to stop piling up.
 */
async function pruneAssets(cache) {
  const requests = await cache.keys();
  const referenced = new Set();
  for (const request of requests) {
    const { pathname } = new URL(request.url);
    const response = await cache.match(request);
    if (pathname.endsWith(".css")) {
      // Stylesheets point at fonts relative to themselves: url(../media/x.woff2).
      for (const [, ref] of (await response.text()).matchAll(CSS_URL))
        referenced.add(new URL(ref, request.url).pathname);
    } else if (
      (response.headers.get("Content-Type") || "").includes("text/html")
    ) {
      for (const asset of (await response.text()).match(ASSET) || [])
        referenced.add(asset);
    }
  }
  for (const request of requests) {
    const path = new URL(request.url).pathname;
    if (path.startsWith("/_next/static/") && !referenced.has(path))
      await cache.delete(request);
  }
}

/**
 * Brings the offline copy in line with the public index: drops papers and news that were withdrawn,
 * then stores pages that are new. The index lists every public paper and news story.
 */
async function sync({ force = false } = {}) {
  if (!force && Date.now() - lastSync < SYNC_INTERVAL_MS) return;
  lastSync = Date.now();
  const cache = await caches.open(CACHE);
  let response;
  try {
    response = await fetch(INDEX, { cache: "no-cache" });
  } catch {
    return;
  }
  if (!storable(response)) return;
  const index = await response.clone().json();
  await cache.put(new URL(INDEX, self.location.origin).href, response);
  const keep = new Set([...SHELL, ...index.map((entry) => entry.path)]);
  for (const request of await cache.keys()) {
    const path = new URL(request.url).pathname;
    if (WITHDRAWABLE.test(path) && !keep.has(path)) await cache.delete(request);
  }
  for (const path of keep) {
    if (!(await cache.match(new URL(path, self.location.origin).href)))
      await store(cache, path);
  }
  await pruneAssets(cache);
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      for (const path of SHELL) await store(cache, path);
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Also clears the current site's caches (seminar-hegemon-*) once the domain moves here.
      const stale = (await caches.keys()).filter(
        (key) => /^(guthub|seminar-hegemon)-/.test(key) && key !== CACHE,
      );
      await Promise.all(stale.map((key) => caches.delete(key)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "sync")
    event.waitUntil(sync({ force: event.data.force === true }));
});

self.addEventListener("fetch", (event) => {
  if (!handles(event.request)) return;
  const { pathname } = new URL(event.request.url);
  event.respondWith(
    pathname.startsWith("/_next/static/")
      ? cacheFirst(event.request)
      : networkFirst(event.request),
  );
});
