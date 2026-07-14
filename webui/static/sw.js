// ─── Olympus UI — Service Worker ─────────────────────────────
// Handles push notifications and offline caching.
//
// Cache strategy:
//   - Navigation requests (HTML): network-first, fall back to cached shell
//   - Static assets (hashed JS/CSS/images): cache-first, fall back to network
//   - API requests: pass through, never cache
//
// This fixes the "stale index.html references missing bundle → black screen"
// bug: old version cached `/` and `/olympus/` on install and never refreshed,
// so a new deploy with a new bundle hash would render against stale HTML.

const CACHE_NAME = 'olympus-v5'
const RUNTIME_CACHE = 'olympus-runtime-v5'
const SHELL_URLS = [
  '/olympus/',
  '/static/manifest.json',
]

// ─── Install: pre-cache the shell, then take over ───────────

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS))
  )
  self.skipWaiting()
})

// ─── Activate: drop old caches, claim open clients ───────────

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== RUNTIME_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  )
  self.clients.claim()
})

// ─── Helpers ─────────────────────────────────────────────────

const isNavigation = (req) =>
  req.mode === 'navigate' ||
  (req.method === 'GET' && req.headers.get('accept')?.includes('text/html'))

const isStaticAsset = (url) =>
  url.pathname.startsWith('/static/') ||
  url.pathname.startsWith('/assets/') ||
  /\.(?:js|css|png|jpg|jpeg|svg|webp|ico|woff2?|ttf|otf)(\?.*)?$/.test(url.pathname)

const isApi = (url) => url.pathname.startsWith('/api/')

// ─── Fetch ───────────────────────────────────────────────────

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return

  let url
  try { url = new URL(req.url) } catch { return }
  if (url.origin !== self.location.origin) return
  if (isApi(url)) return

  // Navigation: network-first so new deploys are picked up immediately.
  // If offline, serve the cached shell so the SPA can boot.
  if (isNavigation(req)) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone()
          caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {})
          return res
        })
        .catch(() => caches.match(req).then((cached) => cached || caches.match('/olympus/')))
    )
    return
  }

  // Static assets: cache-first. Hashed filenames change on every build, so a
  // hit is always safe and a miss just goes to the network.
  if (isStaticAsset(url)) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached
        return fetch(req).then((res) => {
          if (res.ok && res.type === 'basic') {
            const copy = res.clone()
            caches.open(RUNTIME_CACHE).then((c) => c.put(req, copy)).catch(() => {})
          }
          return res
        })
      })
    )
    return
  }

  // Everything else (manifest, sw.js itself, etc.): network with cache fallback
  event.respondWith(
    fetch(req).catch(() => caches.match(req))
  )
})

// ─── Push: show notification when push arrives ──────────────

self.addEventListener('push', (event) => {
  let data = {}

  if (event.data) {
    try {
      data = event.data.json()
    } catch {
      data = { title: event.data.text() }
    }
  }

  const title = data.title || 'Pantheon Notification'
  const options = {
    body: data.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    tag: data.tag || 'pantheon-default',
    data: data.data || {},
    vibrate: [200, 100, 200],
    requireInteraction: true,
  }

  event.waitUntil(self.registration.showNotification(title, options))
})

// ─── Notification click: open / focus the app ───────────────

self.addEventListener('notificationclick', (event) => {
  event.notification.close()

  const targetPath = event.notification.data?.url || '/olympus/'
  const urlToOpen = new URL(targetPath, self.location.origin).toString()

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.startsWith(urlToOpen) && 'focus' in client) {
          return client.focus()
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(urlToOpen)
      }
    })
  )
})
