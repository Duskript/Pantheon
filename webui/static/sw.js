/**
 * Hermes WebUI Service Worker
 * Minimal PWA service worker — enables "Add to Home Screen".
 * No offline caching of API responses (the UI requires a live backend).
 * Caches only static shell assets so the app shell loads fast on repeat visits.
 */

// Cache version is injected by the server at request time (routes.py /sw.js handler).
// Bumps automatically whenever the git commit changes — no manual edits needed.
// Bump to force SW cache refresh: 2026-05-10
// 2026-05-11: ideas edit modal — click-to-edit with inline onclick, backdrop close, section/status/notes editing
const CACHE_NAME = 'hermes-shell-__WEBUI_VERSION__-v3';

// Static assets that form the app shell.
//
// Versioned assets (CSS + JS) include `?v=__WEBUI_VERSION__` to match the
// query string the page sends — see index.html. Without the version query
// here, every cache lookup against `?v=...` URLs would miss and fall through
// to network, defeating the pre-cache.
//
// Do not pre-cache './' or login assets here: under password auth they can be
// either the authenticated app shell or login code, and stale cached responses
// can make valid password submits fail until the user clears browser cache.
// Navigations populate './' only after a successful non-redirect network load.
const VQ = '?v=__WEBUI_VERSION__';
const SHELL_ASSETS = [
  './static/style.css' + VQ,
  './static/ui.js' + VQ,
  './static/messages.js' + VQ,
  './static/sessions.js' + VQ,
  './static/commands.js' + VQ,
  './static/icons.js' + VQ,
  './static/i18n.js' + VQ,
  './static/workspace.js' + VQ,
  './static/terminal.js' + VQ,
  './static/onboarding.js' + VQ,
  './static/favicon-512.png',
  './static/favicon-32.png',
  './manifest.json',
];

// Install: pre-cache the app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(SHELL_ASSETS).catch((err) => {
        // Non-fatal: if any asset fails, still activate
        console.warn('[sw] Shell pre-cache partial failure:', err);
      });
    })
  );
  self.skipWaiting();
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Fetch strategy:
// - API calls (/api/*, /stream) → always network (never cache)
// - Login assets → always network (never cache stale auth code)
// - Page navigations → network-first so auth redirects/cookies are honored
// - Shell assets → cache-first with network fallback
// - Everything else → network-only
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Never intercept cross-origin requests
  if (url.origin !== self.location.origin) return;

  // Never intercept the service worker script itself. Returning a cached sw.js
  // prevents the browser from seeing a new cache version after local patches.
  if (url.pathname.endsWith('/sw.js')) return;

  // Login assets must always hit the network. Older login.js builds have had
  // subpath-sensitive auth POST paths; if the service worker caches one, the
  // password can keep failing until the user manually clears browser cache.
  if (
    url.pathname.endsWith('/login') ||
    url.pathname.endsWith('/static/login.js')
  ) {
    return;
  }

  // API and streaming endpoints — always go to network.
  // The WebUI may be mounted under a subpath such as /hermes/, so API
  // requests can look like /hermes/api/sessions rather than /api/sessions.
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.includes('/api/') ||
    url.pathname.includes('/stream') ||
    url.pathname.startsWith('/health') ||
    url.pathname.includes('/health')
  ) {
    return; // let browser handle normally
  }

  // Page navigations must be network-first. A stale cached './' response can
  // otherwise hide the server's 302-to-login after auth expiry, or ignore a
  // freshly set login cookie until the user manually refreshes.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).then((response) => {
        if (
          event.request.method === 'GET' &&
          response.status === 200 &&
          !response.redirected
        ) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put('./', clone));
        }
        return response;
      }).catch(() => {
        return caches.match('./').then((cached) => cached || new Response(
          '<html><body style="font-family:sans-serif;padding:2rem;background:#1a1a1a;color:#ccc">' +
          '<h2>You are offline</h2>' +
          '<p>Hermes requires a server connection. Please check your network and try again.</p>' +
          '</body></html>',
          { headers: { 'Content-Type': 'text/html' } }
        ));
      })
    );
    return;
  }

  // Only explicit shell assets use cache-first. Everything else should hit the
  // network so stale one-off files (especially auth/login scripts) do not get
  // trapped in CacheStorage until a manual cache clear.
  const scopePath = new URL(self.registration.scope).pathname;
  const relPath = url.pathname.startsWith(scopePath)
    ? url.pathname.slice(scopePath.length)
    : url.pathname.replace(/^\/+/, '');
  const shellPath = './' + relPath.replace(/^\/+/, '') + url.search;
  if (!SHELL_ASSETS.includes(shellPath)) return;

  // Shell assets: stale-while-revalidate
  // Serve cached version instantly for speed, but always fetch from network
  // in the background so the cache is fresh next time. This prevents users
  // from getting stuck on old cached CSS/JS after updates.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      // Background fetch to update the cache
      var fetchPromise = fetch(event.request).then((response) => {
        if (
          event.request.method === 'GET' &&
          response.status === 200
        ) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) { cache.put(event.request, clone); });
        }
        return response;
      }).catch(function() { /* network offline — fine, use cache */ });

      // Return cached immediately, or wait for network if nothing cached
      return cached || fetchPromise;
    })
  );
});

// ── PWA Push Notifications ──────────────────────────────────────────────────
//
// Handles incoming push events and notification clicks.

self.addEventListener('push', function(event) {
  var data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data = { title: 'Pantheon Notification', body: event.data.text() };
    }
  }
  var title = data.title || '🏛️ Pantheon';
  var options = {
    body: data.body || '',
    icon: 'static/favicon-512.png',
    badge: 'static/favicon-192.png',
    tag: data.tag || 'pantheon-notif',
    data: data.data || {},
    vibrate: [200, 100, 200],
    requireInteraction: true,
    silent: false,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  var urlToOpen = event.notification.data && event.notification.data.url
    ? event.notification.data.url
    : self.location.origin + '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
      for (var i = 0; i < clientList.length; i++) {
        var client = clientList[i];
        if (client.url === urlToOpen && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(urlToOpen);
    })
  );
});
