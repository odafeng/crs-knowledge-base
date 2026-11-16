import type { Metadata } from "next";
import { ModerationQueue } from "@/components/moderation";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `留言審核｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default function ModerationPage() {
  return (
    <div className="container page">
      <header className="page-head">
        <h1>留言審核</h1>
        <p className="page-head__lead">
          等待第一次審核或被檢舉的留言。每個處理動作與查看作者都會連同原因記錄。
        </p>
      </header>
      <div className="page__narrow">
        <ModerationQueue />
      </div>
    </div>
  );
}
