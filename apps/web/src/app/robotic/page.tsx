import type { Metadata } from "next";
import { connection } from "next/server";
import { TopicIndex } from "@/components/topic-index";
import { ROBOTIC } from "@/lib/site";

export const metadata: Metadata = {
  title: "機器手臂手術｜GutHub",
  description: "機器手臂 TME 與吻合的試驗實證。",
};

export default async function Page() {
  // Rendered per request so `next build` never calls the API; API reads stay cached for 300 s (lib/content.ts).
  await connection();
  return <TopicIndex crumbs={ROBOTIC} groups={["robotic"]} />;
}
