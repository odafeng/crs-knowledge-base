import { loadFeeds, respond } from "@/lib/feed-routes";
import { toRss } from "@/lib/seo";

export async function GET() {
  const { feeds, topics } = await loadFeeds();
  return respond(toRss(feeds[0], topics), "application/rss+xml");
}
