const CACHE_NAME = 'crs-kb-v14';
const ASSETS = [
  './',
  './index.html',
  './data/papers.json',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './docs/mCRC-BRAF-V600E/Kopetz_NEJM_2019_BEACON.html',
  './docs/mCRC-BRAF-V600E/Tabernero_JCO_2021_BEACON.html',
  './docs/mCRC-BRAF-V600E/Kopetz_NatMed_2025_BREAKWATER.html',
  './docs/mCRC-BRAF-V600E/Elez_NEJM_2025_BREAKWATER.html',
  './docs/mCRC-BRAF-V600E/Kopetz_ESMO_2025_BREAKWATER_ctDNA.html',
  './docs/mCRC-BRAF-V600E/Kopetz_ESMO_2025_BREAKWATER_SubsequentTx.html',
  './docs/mCRC-BRAF-V600E/Kopetz_ASCOGI_2026_BREAKWATER_Cohort3.html',
  './docs/robotic-surgery/Mertens_BJSOpen_2026_SwedishRegistry.html'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Network-first: try network, fallback to cache
// Only cache GET requests with successful (2xx) responses from same origin
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;

  e.respondWith(
    fetch(e.request)
      .then(res => {
        if (res.ok && res.type !== 'opaque' && new URL(e.request.url).origin === self.location.origin) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
