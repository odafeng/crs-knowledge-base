// Shared by the feed, sitemap and robots route handlers.
import { connection } from "next/server";
import { listNews, listPapers, listTopics } from "./content";
import { feeds } from "./seo";

/** Request-time only (the build never calls the API); API reads keep their 300 s cache. */
export async function loadFeeds() {
  await connection();
  const [papers, news, topics] = await Promise.all([
    listPapers(),
    listNews(),
    listTopics(),
  ]);
  return { papers, news, topics, feeds: feeds(papers, news, topics) };
}

export function respond(body: string, type: string): Response {
  return new Response(body, {
    headers: {
      "Content-Type": `${type}; charset=utf-8`,
      "Cache-Control": "public, max-age=300",
    },
  });
}
