import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import {
  AiChip,
  Alerts,
  Breadcrumb,
  KeyStat,
  Phrases,
} from "@/components/reading";
import { listNews, listPapers, listTopics } from "@/lib/content";
import { isUnreviewed, NEWS, newsPath, topicPath } from "@/lib/site";

export const metadata: Metadata = {
  title: "最新消息｜GutHub",
  description: "新文獻的新聞稿。由 AI 依本站的文獻條目撰寫並標示。",
};

export default async function NewsIndex() {
  await connection();
  const [news, papers, topics] = await Promise.all([
    listNews(),
    listPapers(),
    listTopics(),
  ]);
  return (
    <div className="container page">
      <Breadcrumb crumbs={NEWS} />
      <header className="page-head">
        <h1>最新消息</h1>
        <p className="page-head__lead">
          重要的新文獻會寫成一則消息：發生了什麼、關鍵數字、為什麼重要、有什麼限制。這些新聞稿由
          AI 依本站的文獻條目撰寫。
        </p>
      </header>
      <div className="page__narrow">
        <Alerts />
      </div>
      <ol className="news-list page__section">
        {news.map((item) => {
          const paper = papers.find((p) => p.id === item.paperId);
          const topic = topics.find((t) => t.key === paper?.topic);
          return (
            <li className="news-row" key={item.id}>
              <p className="eyebrow">
                <time dateTime={item.publishedAt}>{item.publishedAt}</time>
                {topic && (
                  <Link className="eyebrow__topic" href={topicPath(topic)}>
                    {topic.label}
                  </Link>
                )}
                {paper && (
                  <span>
                    {paper.journal} {paper.year}
                  </span>
                )}
                <AiChip label="AI 新聞稿" />
                {isUnreviewed(item) && <AiChip label="AI 未審" />}
              </p>
              <h2 className="phrased">
                <Link href={newsPath(item)}>
                  <Phrases item={item} />
                </Link>
              </h2>
              <p className="news-row__dek">{item.dek}</p>
              <KeyStat item={item} className="news-row__stat" />
            </li>
          );
        })}
      </ol>
    </div>
  );
}
