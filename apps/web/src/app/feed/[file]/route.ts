import { loadFeeds, respond } from "@/lib/feed-routes";
import { toRss } from "@/lib/seo";

/** /feed/news.xml and one RSS feed per topic with content (/feed/{topic slug}.xml). */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ file: string }> },
) {
  const { file } = await params;
  const { feeds, topics } = await loadFeeds();
  const feed = feeds.find((f) => f.path === `/feed/${file}`);
  if (!feed) return new Response("Not found", { status: 404 });
  return respond(toRss(feed, topics), "application/rss+xml");
}
