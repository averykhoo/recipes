module.exports = {
  globDirectory: '.jekyll-build/_site/',
  globPatterns: [
    '**/*.{html,css,js,json,png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,eot}'
  ],
  swDest: '.jekyll-build/_site/sw.js',
  skipWaiting: true,
  clientsClaim: true,
  runtimeCaching: [
    {
      urlPattern: /^https:\/\/cdn\.jsdelivr\.net\/.*/i,
      handler: 'CacheFirst',
      options: {
        cacheName: 'jsdelivr-cache',
        expiration: {
          maxEntries: 20,
          maxAgeSeconds: 60 * 60 * 24 * 365,
        },
      },
    }
  ]
};
