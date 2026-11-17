import type { Metadata } from "next";
import { connection } from "next/server";
import { TopicChoices } from "@/components/followed-topics";
import { AccountSettings } from "@/components/sign-in";
import { listTopics } from "@/lib/content";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `帳號設定｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default async function AccountPage() {
  // Rendered per request so `next build` never calls the API; the topic list is public and cached (lib/content.ts).
  await connection();
  const topics = (await listTopics()).map((t) => ({
    key: t.key,
    label: t.label,
  }));
  return (
    <div className="container page">
      <header className="page-head">
        <h1>帳號設定</h1>
      </header>
      <div className="page__narrow">
        <AccountSettings />
        <TopicChoices topics={topics} />
      </div>
    </div>
  );
}
