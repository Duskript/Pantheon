// ─── Olympus UI — Service Worker ─────────────────────────────
// Handles push notifications and basic offline caching.

const CACHE_NAME = 'olympus-v1'
const ASSETS_TO_CACHE = [
  '/',
  '/olympus/',
]

// ─── Install: cache shell assets ────────────────────────────

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE)
    })
  )
  self.skipWaiting()
})

// ─── Activate: clean old caches ──────────────────────────────

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME)
          .map((k) => caches.delete(k))
      )
    )
  )
  self.clients.claim()
})

// ─── Fetch: serve from cache, fallback to network ────────────

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return
  if (event.request.url.includes('/api/')) return

  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request)
    })
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
    icon: '/favicon.svg',
    badge: '/favicon.svg',
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

  const urlToOpen = '/olympus/'

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes(urlToOpen) && 'focus' in client) {
          return client.focus()
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(urlToOpen)
      }
    })
  )
})
