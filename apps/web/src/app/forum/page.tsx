import type { Metadata } from "next";
import { connection } from "next/server";
import { ForumHome } from "@/components/forum";
import { listTopics } from "@/lib/content";
import { SITE_NAME } from "@/lib/seo";

// Members only (ADR-0022): the HTML holds no forum content, and search engines are told to stay away.
export const metadata: Metadata = {
  title: `大腸直腸外科論壇｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default async function ForumPage() {
  // Rendered per request so `next build` never calls the API; the topic list is public and cached (lib/content.ts).
  await connection();
  const topics = (await listTopics()).map((t) => ({
    key: t.key,
    label: t.label,
  }));
  return (
    <div className="container page">
      <header className="page-head">
        <h1>大腸直腸外科論壇</h1>
        <p className="page-head__lead">
          驗證過的大腸直腸外科醫師之間的討論。貼文是個人意見，不是本站的文獻整理。
        </p>
      </header>
      <ForumHome topics={topics} />
    </div>
  );
}
