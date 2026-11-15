// Serves a built site from disk at its production URL, so absolute links and the base path behave as on GitHub Pages.
const fs = require('fs');
const path = require('path');

const ORIGIN = 'https://odafeng.github.io';
const BASE = '/crs-knowledge-base/';
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json',
  '.xml': 'application/xml', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.webmanifest': 'application/manifest+json',
};
// One of each page type; two stories, two topics and two papers cover the short and the long variants.
const PAGES = ['', 'news/', 'news/niche2-five-year/', 'news/ifebemtinib-garsorasib/', 'updates/', 'topics/', 'mcrc/',
  'mcrc/braf-v600e/', 'mcrc/msi-h/', 'papers/beacon-2019/', 'papers/stellar303-lancet-2025/', 'robotic/', 'robotic/tme/',
  'robotic/anastomosis/', 'subscribe/', 'about/'];

// `mounts` maps a URL prefix to another folder, e.g. { '/__noto/': fontDir } for screenshot-only assets.
function serve(page, site, mounts = {}) {
  return page.route(ORIGIN + '/**', route => {
    const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
    const prefix = Object.keys(mounts).find(key => pathname.startsWith(key));
    let file = prefix ? path.join(mounts[prefix], pathname.slice(prefix.length)) : path.join(site, pathname.replace(BASE, ''));
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: 'not found' });
    route.fulfill({ status: 200, contentType: TYPES[path.extname(file)] || 'text/plain', body: fs.readFileSync(file) });
  });
}

module.exports = { ORIGIN, BASE, PAGES, serve };
