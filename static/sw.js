// Service worker: shows a notification when a news story is pushed and opens the story when it is tapped.
// The payload is JSON: { title, body, url, tag }. `url` is relative to the site root, so it works under any base path.

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(ASSETS);
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith('seminar-hegemon-') && key !== CACHE_NAME).map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || !event.request.url.startsWith(self.registration.scope)) return;
  event.respondWith(fetch(event.request).catch(async () => {
    const cache = await caches.open(CACHE_NAME);
    return await cache.match(event.request, { ignoreSearch: true }) || Response.error();
  }));
});

self.addEventListener('push', event => {
  const story = event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(story.title || 'Seminar Hegemon', {
    body: story.body || '',
    icon: 'icons/icon-192.png',
    badge: 'icons/badge-96.png',
    tag: story.tag,            // a later push about the same story replaces the earlier one
    lang: 'zh-Hant-TW',
    data: { url: story.url || './' },
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(event.notification.data.url, self.registration.scope).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const open = windows.find(client => client.url === target);
    return open ? open.focus() : self.clients.openWindow(target);
  })());
});
