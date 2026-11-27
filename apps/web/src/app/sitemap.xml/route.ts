import { loadFeeds, respond } from "@/lib/feed-routes";
import { sitemapPages, sitemapXml } from "@/lib/seo";

export async function GET() {
  const { papers, news, topics, events } = await loadFeeds();
  return respond(
    sitemapXml(sitemapPages(papers, news, topics, events)),
    "application/xml",
  );
}
