import type { Metadata } from "next";
import { pageJsonLd, pageMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/reading";
import { connection } from "next/server";
import { TopicIndex } from "@/components/topic-index";
import { TOPICS } from "@/lib/site";

export const metadata: Metadata = pageMetadata(
  "主題",
  "依主題整理的試驗實證。",
  "/topics/",
);

export default async function Page() {
  // Rendered per request so `next build` never calls the API; API reads stay cached for 300 s (lib/content.ts).
  await connection();
  return (
    <>
      <JsonLd
        data={pageJsonLd("主題", "依主題整理的試驗實證。", "/topics/", TOPICS)}
      />
      <TopicIndex crumbs={TOPICS} groups={["mcrc", "robotic"]} />
    </>
  );
}
