---
layout: null
---
// Version cache using Unix timestamp for cleanliness
const CACHE_NAME = 'recipes-{{ site.time | date: "%s" }}';

const PRECACHE_ASSETS = [
  {{ "/" | relative_url | jsonify }},

  // 1. All Collection Docs (Recipes)
  {% for collection in site.collections -%}
    {% for doc in collection.docs -%}
      {{ doc.url | relative_url | jsonify }},
    {% endfor -%}
  {% endfor -%}

  // 2. Standalone Pages
  {% for p in site.pages -%}
    {%- if p.url != "/sw.js" and p.url != "/manifest.json" and p.url != "/robots.txt" and p.url != "/sitemap.xml" -%}
      {{ p.url | relative_url | jsonify }},
    {%- endif -%}
  {% endfor -%}

  // 3. Filtered Static Assets (Ignore Python scripts, txt files)
  {% for file in site.static_files -%}
    {% assign ext = file.extname | downcase %}
    {% if ext == '.png' or ext == '.jpg' or ext == '.jpeg' or ext == '.ico' or ext == '.pdf' or ext == '.css' or ext == '.js' %}
      {{ file.url | relative_url | jsonify }},
    {% endif %}
  {% endfor -%}
];

// Clean out empty lines and duplicates
const UNIQUE_ASSETS = [...new Set(PRECACHE_ASSETS)].filter(url => url && url.trim() !== '');

self.addEventListener('install', event => {
  // Activate immediately - enables silent updates
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME).then(async cache => {
      console.log(`Precaching ${UNIQUE_ASSETS.length} assets...`);

      // Use a concurrency limit to avoid overwhelming the network stack while still being faster than sequential
      const CONCURRENCY_LIMIT = 5;
      const assets = [...UNIQUE_ASSETS];
      const results = [];

      async function worker() {
        while (assets.length > 0) {
          const url = assets.shift();
          try {
            // cache: 'no-cache' forces the browser to ask GitHub Pages: "Has this changed?"
            // If no, GitHub sends 304 Not Modified (0 bytes). Browser gives SW the file from disk.
            // If yes, GitHub sends 200 OK with new content. Delta update achieved natively.
            const request = new Request(url, { cache: 'no-cache' });
            const response = await fetch(request);
            if (response.ok) {
              await cache.put(request, response);
              results.push({ url, status: 'ok' });
            } else {
              console.warn(`Failed to cache ${url}: ${response.status} ${response.statusText}`);
              results.push({ url, status: 'fail', code: response.status });
            }
          } catch (error) {
            console.warn(`Failed to cache ${url}:`, error);
            results.push({ url, status: 'error', error: error.message });
          }
        }
      }

      const workers = Array(Math.min(CONCURRENCY_LIMIT, assets.length)).fill(null).map(worker);
      await Promise.all(workers);

      const succeeded = results.filter(r => r.status === 'ok').length;
      console.log(`Precaching complete. Succeeded: ${succeeded}/${UNIQUE_ASSETS.length}`);
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      // Delete old versions of the cache
      return Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      );
    }).then(() => self.clients.claim()) // Immediately take control of the page
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

      // If the request is for index.html, try to match the directory path (with trailing slash) as well,
      // since Jekyll canonical URLs typically use trailing slashes instead of index.html.
      if (url.pathname.endsWith('/index.html')) {
        const directoryPath = url.pathname.substring(0, url.pathname.length - 10);
        const directoryUrl = new URL(url.href);
        directoryUrl.pathname = directoryPath;
        requestToMatch = directoryUrl.href;
      }

      // Ignore query strings (e.g., ?search=foo) to ensure cache matches
      let cachedResponse = await cache.match(requestToMatch, { ignoreSearch: true });

      // If we modified the request and missed, try the original request just in case
      if (!cachedResponse && requestToMatch !== event.request) {
        cachedResponse = await cache.match(event.request, { ignoreSearch: true });
      }

      // Cache-First: Return from cache immediately. Fallback to network only if missing.
      if (cachedResponse) {
        return cachedResponse;
      }

      // Fallback: If it wasn't precached, fetch it and cache it for next time
      try {
        const networkResponse = await fetch(event.request);
        if (networkResponse.ok) {
          cache.put(event.request, networkResponse.clone());
        }
        return networkResponse;
      } catch (error) {
        // Here you could return a generic offline.html page if implemented
        return new Response('You are offline and this recipe is not cached.', { status: 503 });
      }
    })()
  );
});
