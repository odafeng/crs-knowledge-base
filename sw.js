const CACHE_NAME = 'seminar-hegemon-v19';
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
  './docs/robotic-surgery/Mertens_BJSOpen_2026_SwedishRegistry.html',
  './docs/generic-CRS/Hecht_Lancet_2025_STELLAR303.html',
  './docs/generic-CRS/Hoyek_DLD_2025_NMA3L.html',
  './docs/generic-CRS/Liu_NatCommun_2025_RegoSinti.html',
  './docs/mCRC-BRAF-V600E/Benson_JNCCN_2026_NCCN_ColonCancer_v3.html',
  './docs/mCRC-KRAS-G12C/Song_LancetOncol_2026_IfebemtinibGarsorasib.html',
  './docs/mCRC-MSI-H/Chalabi_Lancet_2026_NICHE2_OS.html',
  './docs/mCRC-MSI-H/Cercek_AnnOncol_2026_AZUR1.html',
  './docs/mCRC-MSI-H/Ghelardi_NatMed_2026_UNICORN.html',
  './docs/mCRC-MSI-H/Li_FrontImmunol_2026_PD1_WatchAndWait.html',
  './docs/robotic-surgery/Song_BrJSurg_2026_COLRAR_LongTerm.html',
  './docs/robotic-surgery/Genders_BJS_2026_RestorativeMA.html'
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
