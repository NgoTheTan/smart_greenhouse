// GreenHub service worker - Web Push (spec 10)
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('push', (e) => {
  const d = e.data ? e.data.json() : { title: 'GreenHub', body: '' }
  e.waitUntil(
    self.registration.showNotification(d.title, {
      body: d.body,
      tag: d.tag,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      requireInteraction: d.severity === 'critical',
      data: { url: d.url || '/' },
    }),
  )
})

self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  e.waitUntil(clients.openWindow(e.notification.data.url))
})

