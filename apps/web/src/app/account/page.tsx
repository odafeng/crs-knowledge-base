import type { Metadata } from "next";
import { connection } from "next/server";
import { TopicChoices } from "@/components/followed-topics";
import { FollowedPapers } from "@/components/paper-follows";
import { AccountSettings } from "@/components/sign-in";
import { SurgeonMembership } from "@/components/surgeon-membership";
import { listPapers, listTopics } from "@/lib/content";
import { SITE_NAME } from "@/lib/seo";
import { paperPath, paperTitle } from "@/lib/site";

export const metadata: Metadata = {
  title: `帳號設定｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default async function AccountPage() {
  // Rendered per request so `next build` never calls the API; topics and papers are public and cached (lib/content.ts).
  await connection();
  const [topicList, paperList] = await Promise.all([
    listTopics(),
    listPapers(),
  ]);
  const topics = topicList.map((t) => ({ key: t.key, label: t.label }));
  // Every public paper's name, so the browser can name what the reader follows without the server knowing it.
  const papers = paperList.map((p) => ({
    id: p.id,
    title: paperTitle(p),
    path: paperPath(p),
  }));
  return (
    <div className="container page">
      <header className="page-head">
        <h1>帳號設定</h1>
      </header>
      <div className="page__narrow">
        <AccountSettings />
        <TopicChoices topics={topics} />
        <FollowedPapers papers={papers} />
        <SurgeonMembership />
      </div>
    </div>
  );
}
