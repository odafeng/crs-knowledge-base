import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { ReviewQueue } from "@/components/review-queue";
import { listNews, listPapers } from "@/lib/content";
import { pendingReview } from "@/lib/review";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `待審內容｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default async function ReviewPage() {
  // Rendered per request so `next build` never calls the API; the lists are public and cached (lib/content.ts).
  await connection();
  const [papers, news] = await Promise.all([listPapers(), listNews()]);
  return (
    <div className="container page">
      <header className="page-head">
        <h1>待審內容</h1>
        <p className="page-head__lead">
          AI 自動發布、標示「AI
          未審」的文獻與消息。點標題看全文，確認後按「標為已審」；有錯就「撤下」。
          結果約一分鐘後套用，頁面最多 5 分鐘內更新。留言在
          <Link href="/admin/comments/">留言審核</Link>。
        </p>
      </header>
      <div className="page__narrow">
        <ReviewQueue items={pendingReview(papers, news)} />
      </div>
    </div>
  );
}
