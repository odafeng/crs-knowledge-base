import { loadFeeds, respond } from "@/lib/feed-routes";
import { searchIndex } from "@/lib/search";

/** The search index at the address the current site uses; the service worker keeps a copy for offline search. */
export async function GET() {
  const { papers, news, topics, events } = await loadFeeds();
  return respond(
    JSON.stringify(searchIndex(papers, news, topics, events)),
    "application/json",
  );
}
