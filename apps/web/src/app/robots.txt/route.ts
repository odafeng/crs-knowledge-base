import { robotsTxt } from "@/lib/seo";

export function GET() {
  // Before the site is public (GUTHUB_SITE_PUBLIC), every page also carries noindex; see lib/seo.ts robots().
  return new Response(robotsTxt(), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
