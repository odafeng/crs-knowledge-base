import type { Metadata } from "next";
import Link from "next/link";
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
        <p className="comment__meta">
          <Link className="thread-head__back" href="/forum/">
            ← 回醫師論壇
          </Link>
        </p>
        <h1>開新話題</h1>
        <p className="page-head__lead">
          與通過驗證的大腸直腸外科同儕交流臨床案例、指引解讀或手術經驗。
        </p>
      </header>
      {/* The form reads ?paperId= and ?anonymous= from the URL. */}
      <Suspense fallback={<p aria-live="polite">載入中…</p>}>
        <NewThread topics={topics} />
      </Suspense>
    </div>
  );
}
