import type { Metadata } from "next";
import { connection } from "next/server";
import { ForumThread } from "@/components/forum";
import { listTopics } from "@/lib/content";
import { SITE_NAME } from "@/lib/seo";

// The title stays generic: thread titles are members-only and never reach the HTML.
export const metadata: Metadata = {
  title: `論壇話題｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

type Props = { params: Promise<{ id: string }> };

export default async function ForumThreadPage({ params }: Props) {
  await connection();
  const { id } = await params;
  const topics = (await listTopics()).map((t) => ({
    key: t.key,
    label: t.label,
  }));
  return (
    <div className="container page">
      <ForumThread id={id} topics={topics} />
    </div>
  );
}
