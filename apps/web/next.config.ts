import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
// Public index pages read the API at request time (connection()), so Next.js marks them private by default.
// They hold no per-reader data; saying so lets the service worker keep them for offline reading (C3 #65).
// List pages here explicitly: account and admin pages must keep the private default.
const PUBLIC_DYNAMIC_PAGES = [
  "/",
  "/updates/",
  "/news/",
  "/topics/",
  "/mcrc/",
  "/robotic/",
  "/subscribe/",
];

const nextConfig: NextConfig = {
  // The current site's URLs end with a slash (/papers/{slug}/); keep them unchanged.
  trailingSlash: true,
  outputFileTracingRoot: repositoryRoot,
  turbopack: { root: repositoryRoot },
  // Browsers must always check for a new service worker (Next.js PWA guide).
  async headers() {
    return [
      ...PUBLIC_DYNAMIC_PAGES.map((source) => ({
        source,
        headers: [
          { key: "Cache-Control", value: "public, max-age=0, must-revalidate" },
          // Vercel rewrites Cache-Control on dynamic pages to private; the service worker reads this instead.
          { key: "X-GutHub-Public", value: "1" },
        ],
      })),
      // Sign-in pages hold no identity in their HTML (the session stays in the browser), but their URLs carry
      // one-time tokens; keep them out of every shared cache (D1 #67).
      ...["/account/", "/auth/:path*", "/admin/:path*"].map((source) => ({
        source,
        headers: [{ key: "Cache-Control", value: "private, no-store" }],
      })),
      // The forum is members only (ADR-0022): no shared caching, and no indexing even if a crawler finds a link.
      ...["/forum/", "/forum/:path*"].map((source) => ({
        source,
        headers: [
          { key: "Cache-Control", value: "private, no-store" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
        ],
      })),
      {
        source: "/sw.js",
        headers: [
          {
            key: "Cache-Control",
            value: "no-cache, no-store, must-revalidate",
          },
          {
            key: "Content-Security-Policy",
            value: "default-src 'self'; script-src 'self'",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
