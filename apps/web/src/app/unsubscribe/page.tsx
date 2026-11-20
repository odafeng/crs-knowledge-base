import type { Metadata } from "next";
import { connection } from "next/server";
import { Unsubscribe } from "@/components/unsubscribe";
import { listPapers } from "@/lib/content";
import { SITE_NAME } from "@/lib/seo";
import { paperTitle } from "@/lib/site";

export const metadata: Metadata = {
  title: `停止留言通知｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

// The landing page of a digest's unsubscribe links (G8 #119). Nothing changes until the reader presses the button, so
// a mail scanner that opens every link cannot unsubscribe anyone.
export default async function UnsubscribePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await connection();
  const query = await searchParams;
  const one = (value: string | string[] | undefined) =>
    typeof value === "string" && value ? value : null;
  const token = one(query.t);
  const paperId = one(query.paper);
  const paper = paperId
    ? (await listPapers()).find((p) => p.id === paperId)
    : undefined;
  return (
    <div className="container page">
      <header className="page-head">
        <h1>停止留言通知</h1>
      </header>
      <div className="page__narrow">
        <Unsubscribe
          token={token}
          paperId={paperId}
          title={paper ? paperTitle(paper) : null}
        />
      </div>
    </div>
  );
}
