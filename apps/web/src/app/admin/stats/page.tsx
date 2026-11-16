import type { Metadata } from "next";
import { ActivityStats } from "@/components/activity-stats";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `每週活動｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default function ActivityPage() {
  return (
    <div className="container page">
      <header className="page-head">
        <h1>每週活動</h1>
        <p className="page-head__lead">
          只有彙總數字，不列出是誰。活躍讀者指當週有留言、按讚或檢舉的帳號；只登入閱讀的讀者不會被計入。
        </p>
      </header>
      <div className="page__narrow">
        <ActivityStats />
      </div>
    </div>
  );
}
