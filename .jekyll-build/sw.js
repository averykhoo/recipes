---
layout: null
---
// Version cache using Unix timestamp for cleanliness
const CACHE_NAME = 'recipes-{{ site.time | date: "%s" }}';

const PRECACHE_ASSETS = [
  '{{ "/" | relative_url }}',

  // 1. All Collection Docs (Recipes)
  {% for collection in site.collections -%}
    {% for doc in collection.docs -%}
      '{{ doc.url | relative_url }}',
    {% endfor -%}
  {% endfor -%}

  // 2. Standalone Pages
  {% for p in site.pages -%}
    {%- if p.url != "/sw.js" and p.url != "/manifest.json" and p.url != "/robots.txt" and p.url != "/sitemap.xml" -%}
      '{{ p.url | relative_url }}',
    {%- endif -%}
  {% endfor -%}

  // 3. Filtered Static Assets (Ignore Python scripts, txt files)
  {% for file in site.static_files -%}
    {% assign ext = file.extname | downcase %}
    {% if ext == '.png' or ext == '.jpg' or ext == '.jpeg' or ext == '.ico' or ext == '.pdf' or ext == '.css' or ext == '.js' %}
      '{{ file.path | relative_url }}',
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
      // Process files individually so 404s don't kill the whole offline experience
      await Promise.all(UNIQUE_ASSETS.map(async url => {
        try {
          // cache: 'no-cache' forces the browser to ask GitHub Pages: "Has this changed?"
          // If no, GitHub sends 304 Not Modified (0 bytes). Browser gives SW the file from disk.
          // If yes, GitHub sends 200 OK with new content. Delta update achieved natively.
          const request = new Request(url, { cache: 'no-cache' });
          const response = await fetch(request);
          if (response.ok) {
            await cache.put(request, response);
          }
        } catch (error) {
          console.warn(`Failed to cache ${url}:`, error);
        }
      }));
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      // Delete old versions of the cache
      return Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) return caches.delete(key);
        })
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

      // Fix Directory vs Index.html mismatch
      let requestToMatch = event.request;
      if (requestToMatch.url.endsWith('/')) {
        requestToMatch = new Request(requestToMatch.url + 'index.html');
      }

      // Ignore query strings (e.g., ?search=foo) to ensure cache matches
      let cachedResponse = await cache.match(requestToMatch, { ignoreSearch: true });

      // If we miss the modified index, try the original request just in case
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
