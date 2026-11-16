import { loadFeeds, respond } from "@/lib/feed-routes";
import { toAtom } from "@/lib/seo";

/** The full stream as Atom, at the address the current site uses. */
export async function GET() {
  const { feeds, topics } = await loadFeeds();
  return respond(
    toAtom({ ...feeds[0], path: "/atom.xml" }, topics),
    "application/atom+xml",
  );
}
