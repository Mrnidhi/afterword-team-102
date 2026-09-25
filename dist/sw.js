const CACHE='afterword-shell-v1'; const SHELL=['/','/landing.css','/landing.js','/manifest.webmanifest'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))));
self.addEventListener('fetch', event => { if (event.request.method !== 'GET' || new URL(event.request.url).origin !== location.origin) return; event.respondWith(fetch(event.request).catch(() => caches.match(event.request).then(hit => hit || caches.match('/')))); });
