import type { Metadata } from "next";
import { connection } from "next/server";
import { TopicIndex } from "@/components/topic-index";
import { TOPICS } from "@/lib/site";

export const metadata: Metadata = {
  title: "主題｜GutHub",
  description: "依主題整理的試驗實證。",
};

export default async function Page() {
  // Rendered per request so `next build` never calls the API; API reads stay cached for 300 s (lib/content.ts).
  await connection();
  return <TopicIndex crumbs={TOPICS} groups={["mcrc", "robotic"]} />;
}
