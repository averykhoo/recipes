---
layout: null
---
// Version cache using Unix timestamp for cleanliness
const CACHE_NAME = 'recipes-{{ site.time | date: "%s" }}';

const PRECACHE_ASSETS = [
  {{ "/" | relative_url | jsonify }},

  // 1. Precache root indices of the collections
  {% for collection in site.collections -%}
    {{ "/" | append: collection.label | append: "/" | relative_url | jsonify }},
  {% endfor -%}

  // 2. Precache index pages of nested directories
  {% for p in site.pages -%}
    {%- if p.url contains "index.html" or p.url == "/" -%}
      {{ p.url | relative_url | jsonify }},
    {%- endif -%}
  {% endfor -%}

  // 3. Precache critical static design assets only
  {% for file in site.static_files -%}
    {% assign ext = file.extname | downcase %}
    {% if ext == '.css' or ext == '.js' or ext == '.ico' or ext == '.png' %}
      {{ file.url | relative_url | jsonify }},
    {% endif %}
  {% endfor -%}
];

// Clean out empty lines and duplicates
const UNIQUE_ASSETS = [...new Set(PRECACHE_ASSETS)].filter(url => url && url.trim() !== '');

self.addEventListener('install', event => {
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME).then(async cache => {
      console.log(`Precaching shell assets: ${UNIQUE_ASSETS.length}`);

      const CONCURRENCY_LIMIT = 5;
      const assets = [...UNIQUE_ASSETS];
      const results = [];

      async function worker() {
        while (assets.length > 0) {
          const url = assets.shift();
          try {
            const request = new Request(url, { cache: 'no-cache' });
            const response = await fetch(request);
            if (response.ok) {
              await cache.put(request, response);
              results.push({ url, status: 'ok' });
            } else {
              results.push({ url, status: 'fail', code: response.status });
            }
          } catch (error) {
            results.push({ url, status: 'error', error: error.message });
          }
        }
      }

      const workers = Array(Math.min(CONCURRENCY_LIMIT, assets.length)).fill(null).map(worker);
      await Promise.all(workers);
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  // Ignore external CDN requests (like Mermaid.js)
  if (!event.request.url.startsWith(self.location.origin)) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      const url = new URL(event.request.url);
      let requestToMatch = event.request;

      // Robust index.html conversion to directory paths
      if (url.pathname.endsWith('/index.html')) {
        const normalizedPath = url.pathname.replace(/\/index\.html$/, '/');
        const normalizedUrl = new URL(url.href);
        normalizedUrl.pathname = normalizedPath;
        requestToMatch = normalizedUrl.href;
      }

      // Try to find a direct cached response
      let cachedResponse = await cache.match(requestToMatch, { ignoreSearch: true });

      if (!cachedResponse && requestToMatch !== event.request) {
        cachedResponse = await cache.match(event.request, { ignoreSearch: true });
      }

      // Fallback: Resolve extension-less requests to compiled .html pages in cache
      if (!cachedResponse && !url.pathname.endsWith('.html') && !url.pathname.endsWith('/')) {
        const htmlUrl = url.href + '.html';
        cachedResponse = await cache.match(htmlUrl, { ignoreSearch: true });
      }

      // Stale-While-Revalidate: fetch in background, store in cache, return cached response if available
      const fetchPromise = (async () => {
        try {
          const networkResponse = await fetch(event.request);
          if (networkResponse.ok) {
            await cache.put(requestToMatch, networkResponse.clone());
          }
          return networkResponse;
        } catch (err) {
          // Suppress network errors inside background update promise
        }
      })();

      return cachedResponse || fetchPromise;
    })()
  );
});
