/* Cache public application shell only. API responses and photo reports never enter CacheStorage. */
const CACHE = 'naryadai-shell-v1';
const SHELL = ['/', '/web/styles.css', '/web/app.js', '/web/manifest.webmanifest', '/web/icons/icon.svg', '/web/icons/icon-192.png', '/web/icons/icon-512.png', '/assets/branding/km-logo-white.svg'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(async cache => {
    await Promise.all(SHELL.map(async url => {
      try { const response = await fetch(url, {cache: 'reload'}); if (response.ok) await cache.put(url, response); } catch (_) { /* shell available on next successful request */ }
    }));
  }));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('naryadai-shell-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/') || !SHELL.includes(url.pathname)) return;
  event.respondWith(fetch(event.request).then(response => {
    if (response.ok) { const copy = response.clone(); caches.open(CACHE).then(cache => cache.put(url.pathname, copy)); }
    return response;
  }).catch(() => caches.match(url.pathname).then(response => response || Response.error())));
});
self.addEventListener('message', event => {
  if (event.data === 'PURGE_PRIVATE') event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('naryadai-') && !key.startsWith('naryadai-shell-')).map(key => caches.delete(key)))));
});
