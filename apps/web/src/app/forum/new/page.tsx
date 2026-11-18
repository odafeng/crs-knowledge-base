import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";
import { NewThread } from "@/components/forum";
import { listTopics } from "@/lib/content";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `開新話題｜大腸直腸外科論壇｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default async function NewThreadPage() {
  await connection();
  const topics = (await listTopics()).map((t) => ({
    key: t.key,
    label: t.label,
  }));
  return (
    <div className="container page">
      <header className="page-head">
        <h1>開新話題</h1>
      </header>
      <div className="page__narrow">
        {/* The form reads ?paperId= from the URL. */}
        <Suspense fallback={<p aria-live="polite">載入中…</p>}>
          <NewThread topics={topics} />
        </Suspense>
      </div>
    </div>
  );
}
