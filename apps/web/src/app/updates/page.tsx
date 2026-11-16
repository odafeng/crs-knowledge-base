import type { Metadata } from "next";
import { pageJsonLd, pageMetadata } from "@/lib/seo";
import { connection } from "next/server";
import { Breadcrumb, Entry, JsonLd } from "@/components/reading";
import { listPapers, listTopics } from "@/lib/content";
import { HOME, updates } from "@/lib/site";

export const metadata: Metadata = pageMetadata(
  "文獻",
  "依收錄日排列的全部文獻與評論。",
  "/updates/",
);

export default async function UpdatesPage() {
  await connection();
  const [papers, topics] = await Promise.all([listPapers(), listTopics()]);
  const rows = updates(papers);
  const topicOf = (key: string) => topics.find((t) => t.key === key);
  return (
    <div className="container page">
      <JsonLd
        data={pageJsonLd(
          "文獻",
          "依收錄日排列的全部文獻與評論。",
          "/updates/",
          [...HOME, ["文獻", "/updates/"]],
        )}
      />
      <Breadcrumb crumbs={[...HOME, ["文獻", "/updates/"]]} />
      <header className="page-head">
        <h1>文獻</h1>
        <p className="page-head__lead">
          全部收錄的文獻與評論，新的在前，共 {rows.length} 則。
        </p>
      </header>
      {/* The search box returns with C3 (#65), which migrates search and reading preferences. */}
      <ol className="entries page__section page__narrow" id="q">
        {rows.map((update) => (
          <Entry
            update={update}
            topic={topicOf(update.paper.topic)}
            level={2}
            key={update.id}
          />
        ))}
      </ol>
    </div>
  );
}
