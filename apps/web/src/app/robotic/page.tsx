import type { Metadata } from "next";
import { pageJsonLd, pageMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/reading";
import { connection } from "next/server";
import { TopicIndex } from "@/components/topic-index";
import { ROBOTIC } from "@/lib/site";

export const metadata: Metadata = pageMetadata(
  "機器手臂手術",
  "機器手臂 TME、吻合技術與微創大腸直腸外科試驗實證。",
  "/robotic/",
);

export default async function Page() {
  // Rendered per request so `next build` never calls the API; API reads stay cached for 300 s (lib/content.ts).
  await connection();
  return (
    <>
      <JsonLd
        data={pageJsonLd(
          "機器手臂手術",
          "機器手臂 TME、吻合技術與微創大腸直腸外科試驗實證。",
          "/robotic/",
          ROBOTIC,
        )}
      />
      <TopicIndex crumbs={ROBOTIC} groups={["robotic"]} />
    </>
  );
}
