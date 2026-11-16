import type { Metadata } from "next";
import { pageJsonLd, pageMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/reading";
import { connection } from "next/server";
import { TopicIndex } from "@/components/topic-index";
import { MCRC } from "@/lib/site";

export const metadata: Metadata = pageMetadata(
  "mCRC 治療",
  "轉移性大腸直腸癌依分子分型整理的試驗實證。",
  "/mcrc/",
);

export default async function Page() {
  // Rendered per request so `next build` never calls the API; API reads stay cached for 300 s (lib/content.ts).
  await connection();
  return (
    <>
      <JsonLd
        data={pageJsonLd(
          "mCRC 治療",
          "轉移性大腸直腸癌依分子分型整理的試驗實證。",
          "/mcrc/",
          MCRC,
        )}
      />
      <TopicIndex crumbs={MCRC} groups={["mcrc"]} />
    </>
  );
}
