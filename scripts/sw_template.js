/*
 * Service worker source template for the recipes site.
 *
 * This file is not shipped as-is. scripts/build_sw.py walks the built site and
 * replaces the three placeholders below, writing the result to _site/sw.js.
 * The placeholders are written so that this template is still syntactically valid
 * JavaScript, which keeps editors and linters usable while working on it.
 *
 * Caching strategy, in short:
 *
 *   pages (html)  network-first, revalidated  -> a page visit shows the newest
 *                                                version the moment it is deployed
 *   shell (css/js/fonts)  cache-first, keyed by build id
 *   media (images)        stale-while-revalidate
 *
 * The whole site is still available offline: after a new build activates, the
 * worker walks the page manifest in the background and refreshes the page cache
 * without blocking, delaying, or staling any actual page visit.
 */

const BUILD_ID = '__BUILD_ID__';
const SHELL_ASSETS = __SHELL_ASSETS__;
const PAGES = __PAGES__;

/* Shell assets are not content-hashed by Jekyll, so the cache is keyed by build id
 * and dropped wholesale on activate. Pages and media outlive a build: they are
 * revalidated with conditional requests instead, so an unchanged recipe costs a 304
 * rather than a re-download of the whole corpus. */
const SHELL_CACHE = 'shell-' + BUILD_ID;
const PAGE_CACHE = 'pages-v1';
const MEDIA_CACHE = 'media-v1';
const CDN_CACHE = 'cdn-v1';
const KEEP_CACHES = [SHELL_CACHE, PAGE_CACHE, MEDIA_CACHE, CDN_CACHE];

/* How long a page visit waits for the network before falling back to the cached
 * copy. The network request is *not* cancelled when this fires -- it keeps running
 * and refreshes the cache, so a slow connection still converges on fresh content. */
const NETWORK_TIMEOUT_MS = 3500;

/* Parallel fetches used by the background warm. Deliberately modest: this runs on
 * phones, often on mobile data, and is never on the critical path for anything. */
const WARM_CONCURRENCY = 4;

const MEDIA_CACHE_MAX_ENTRIES = 80;
const CDN_CACHE_MAX_ENTRIES = 20;

const BASE = new URL('./', self.location).href;

function toAbsolute(path) {
    return new URL(path, BASE).href;
}

const SHELL_URLS = SHELL_ASSETS.map(toAbsolute);
const PAGE_URLS = PAGES.map(toAbsolute);
const SHELL_URL_SET = new Set(SHELL_URLS);
const PAGE_URL_SET = new Set(PAGE_URLS);

/* A request that bypasses the HTTP cache and revalidates against the server.
 * GitHub Pages serves everything with "Cache-Control: max-age=600", so a plain
 * fetch can hand back ten-minute-old bytes without ever asking the origin. The
 * ETag is still honoured, so an unchanged file comes back as a cheap 304. */
function revalidatingRequest(url) {
    return new Request(url, {
        cache: 'no-cache',
        credentials: 'same-origin',
        redirect: 'follow',
    });
}

function isHtmlRequest(request, url) {
    if (request.mode === 'navigate') {
        return true;
    }
    if (request.destination === 'document') {
        return true;
    }
    const path = url.pathname;
    return path.endsWith('/') || path.endsWith('.html');
}

/* Directory URLs and their backing index.html are the same page but different cache
 * keys, so a lookup for one falls back to the other. */
function indexVariants(url) {
    const variants = [url];
    if (url.endsWith('/')) {
        variants.push(url + 'index.html');
    } else if (url.endsWith('/index.html')) {
        variants.push(url.slice(0, -'index.html'.length));
    }
    return variants;
}

async function matchPage(cache, url) {
    for (const variant of indexVariants(url)) {
        const hit = await cache.match(variant);
        if (hit) {
            return hit;
        }
    }
    return undefined;
}

function offlineResponse() {
    const body = '<!doctype html><meta charset="utf-8">' +
        '<meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<title>Offline</title>' +
        '<style>body{font-family:system-ui,sans-serif;margin:3rem auto;max-width:32rem;' +
        'padding:0 1.5rem;line-height:1.6}</style>' +
        '<h1>Offline</h1>' +
        '<p>This page has not been saved for offline use yet. ' +
        'Reconnect, or head <a href="' + BASE + '">back to the recipe index</a>.</p>';
    return new Response(body, {
        status: 503,
        headers: {'Content-Type': 'text/html; charset=utf-8'},
    });
}

/* Housekeeping only, and it runs in a .finally() attached to the response promise --
 * so it must never reject, or a failed trim would turn a perfectly good response into
 * a network error. */
async function trimCache(cacheName, maxEntries) {
    try {
        const cache = await caches.open(cacheName);
        const keys = await cache.keys();
        for (let i = 0; i < keys.length - maxEntries; i++) {
            await cache.delete(keys[i]);
        }
    } catch (err) {
        /* Ignored: an over-full cache is not worth failing a request over. */
    }
}

/*
 * Strategies
 */

async function pageNetworkFirst(request) {
    const url = new URL(request.url).href;
    const cache = await caches.open(PAGE_CACHE);

    /* Kept alive past the timeout on purpose, so a slow response still lands in the
     * cache for next time rather than being thrown away. */
    const fromNetwork = fetch(revalidatingRequest(url))
        .then(async (response) => {
            if (response && response.ok) {
                await cache.put(url, response.clone());
            }
            return response;
        })
        .catch(() => null);

    const timeout = new Promise((resolve) => setTimeout(() => resolve(null), NETWORK_TIMEOUT_MS));
    const raced = await Promise.race([fromNetwork, timeout]);
    if (raced && raced.ok) {
        return raced;
    }

    const cached = await matchPage(cache, url);
    if (cached) {
        return cached;
    }

    /* Nothing cached: the in-flight request is now the only hope. */
    const settled = await fromNetwork;
    if (settled) {
        return settled;
    }
    return offlineResponse();
}

async function cacheFirst(request, cacheName) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request);
    if (cached) {
        return cached;
    }
    try {
        const response = await fetch(request);
        if (response && (response.ok || response.type === 'opaque')) {
            await cache.put(request, response.clone());
        }
        return response;
    } catch (err) {
        return Response.error();
    }
}

async function staleWhileRevalidate(request, cacheName) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request);

    const fromNetwork = fetch(request)
        .then(async (response) => {
            if (response && response.ok) {
                await cache.put(request, response.clone());
            }
            return response;
        })
        .catch(() => null);

    if (cached) {
        return cached;
    }
    const response = await fromNetwork;
    return response || Response.error();
}

/*
 * Background warm -- the "reload the offline version in the background" half.
 */

async function warmPages() {
    const cache = await caches.open(PAGE_CACHE);
    const queue = PAGE_URLS.slice();
    let cursor = 0;
    let warmed = 0;

    async function worker() {
        while (cursor < queue.length) {
            const url = queue[cursor++];
            try {
                const response = await fetch(revalidatingRequest(url));
                if (response && response.ok) {
                    await cache.put(url, response.clone());
                    warmed++;
                }
            } catch (err) {
                /* Offline, or the network dropped mid-walk. Stop this worker rather
                 * than grinding through the rest of the manifest failing each one;
                 * the next activate or WARM_PAGES message picks it back up. */
                return;
            }
        }
    }

    const workers = [];
    for (let i = 0; i < WARM_CONCURRENCY; i++) {
        workers.push(worker());
    }
    await Promise.all(workers);
    return warmed;
}

/* Drop pages that are no longer in the manifest, so renamed and deleted recipes do
 * not linger offline forever. */
async function prunePages() {
    const cache = await caches.open(PAGE_CACHE);
    const keys = await cache.keys();
    for (const key of keys) {
        const url = new URL(key.url).href;
        const known = indexVariants(url).some((variant) => PAGE_URL_SET.has(variant));
        if (!known) {
            await cache.delete(key);
        }
    }
}

async function announceBuild() {
    const clients = await self.clients.matchAll({includeUncontrolled: true, type: 'window'});
    for (const client of clients) {
        client.postMessage({type: 'BUILD_ACTIVATED', buildId: BUILD_ID});
    }
}

/*
 * Lifecycle
 */

self.addEventListener('install', (event) => {
    event.waitUntil((async () => {
        const cache = await caches.open(SHELL_CACHE);
        /* Individually rather than via addAll: one missing asset should not abort
         * the whole install and leave the site uncached. */
        await Promise.all(SHELL_URLS.map(async (url) => {
            try {
                const response = await fetch(revalidatingRequest(url));
                if (response && response.ok) {
                    await cache.put(url, response);
                }
            } catch (err) {
                /* Ignored: picked up at runtime by the fetch handler. */
            }
        }));
        await self.skipWaiting();
    })());
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const names = await caches.keys();
        await Promise.all(names
            .filter((name) => KEEP_CACHES.indexOf(name) === -1)
            .map((name) => caches.delete(name)));

        await prunePages();
        await self.clients.claim();

        /* Tell open pages first, so they reload onto the new build immediately.
         * The warm below then runs while they are already showing fresh content. */
        await announceBuild();

        await warmPages();
    })());
});

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') {
        return;
    }

    let url;
    try {
        url = new URL(request.url);
    } catch (err) {
        return;
    }

    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
        return;
    }

    if (url.origin !== self.location.origin) {
        if (url.hostname === 'cdn.jsdelivr.net') {
            event.respondWith(cacheFirst(request, CDN_CACHE)
                .finally(() => trimCache(CDN_CACHE, CDN_CACHE_MAX_ENTRIES)));
        }
        return;
    }

    if (isHtmlRequest(request, url)) {
        event.respondWith(pageNetworkFirst(request));
        return;
    }

    if (SHELL_URL_SET.has(url.href)) {
        event.respondWith(cacheFirst(request, SHELL_CACHE));
        return;
    }

    event.respondWith(staleWhileRevalidate(request, MEDIA_CACHE)
        .finally(() => trimCache(MEDIA_CACHE, MEDIA_CACHE_MAX_ENTRIES)));
});

self.addEventListener('message', (event) => {
    const data = event.data || {};
    if (data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    } else if (data.type === 'WARM_PAGES') {
        event.waitUntil(warmPages());
    } else if (data.type === 'GET_BUILD_ID') {
        if (event.source) {
            event.source.postMessage({type: 'BUILD_ID', buildId: BUILD_ID});
        }
    }
});
