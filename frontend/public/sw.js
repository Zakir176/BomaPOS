const SHELL_CACHE = 'bomapos-shell-v2';
const API_CACHE = 'bomapos-api-v2';

const CORE_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/pwa-icon.svg',
  '/favicon.svg',
];

// Install Event: Pre-cache App Shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => {
      console.log('[BomaPOS SW] Caching app shell assets');
      return cache.addAll(CORE_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

// Activate Event: Clean up stale caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== SHELL_CACHE && key !== API_CACHE) {
            console.log('[BomaPOS SW] Clearing obsolete cache:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch Event: Offline-first asset & API caching strategy
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 1. Navigation requests (SPA Shell fallback)
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(async () => {
        const shell = await caches.open(SHELL_CACHE);
        const cachedIndex = await shell.match('/index.html') || await shell.match('/');
        return cachedIndex;
      })
    );
    return;
  }

  // 2. GET /api/menu (Stale-while-revalidate / Network-first with cache fallback)
  if (event.request.method === 'GET' && url.pathname === '/api/menu') {
    event.respondWith(
      fetch(event.request)
        .then(async (response) => {
          if (response.ok) {
            const apiCache = await caches.open(API_CACHE);
            apiCache.put(event.request, response.clone());
          }
          return response;
        })
        .catch(async () => {
          console.log('[BomaPOS SW] Network failed, serving cached menu');
          const apiCache = await caches.open(API_CACHE);
          const cachedMenu = await apiCache.match(event.request);
          if (cachedMenu) {
            return cachedMenu;
          }
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        })
    );
    return;
  }

  // 3. Static assets: JS, CSS, Google Fonts, SVGs (Cache-first / Stale-while-revalidate)
  if (
    url.origin === location.origin ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com')
  ) {
    // Only handle GET requests for static caching
    if (event.request.method === 'GET' && !url.pathname.startsWith('/api/')) {
      event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
          const fetchPromise = fetch(event.request)
            .then((networkResponse) => {
              if (networkResponse && networkResponse.status === 200) {
                const responseToCache = networkResponse.clone();
                caches.open(SHELL_CACHE).then((cache) => {
                  cache.put(event.request, responseToCache);
                });
              }
              return networkResponse;
            })
            .catch(() => cachedResponse);

          return cachedResponse || fetchPromise;
        })
      );
      return;
    }
  }

  // Default: pass through to network
  event.respondWith(fetch(event.request));
});
