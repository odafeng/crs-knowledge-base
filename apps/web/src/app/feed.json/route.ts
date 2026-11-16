import { loadFeeds, respond } from "@/lib/feed-routes";
import { toJsonFeed } from "@/lib/seo";

/** The full stream as JSON Feed 1.1, at the address the current site uses. */
export async function GET() {
  const { feeds, topics } = await loadFeeds();
  return respond(
    toJsonFeed({ ...feeds[0], path: "/feed.json" }, topics),
    "application/feed+json",
  );
}
