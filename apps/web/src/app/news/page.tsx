import type { Metadata } from "next";
import { connection } from "next/server";
import { NewsFeed } from "@/components/news-feed";
import { Alerts, Breadcrumb, JsonLd } from "@/components/reading";
import {
  listNews,
  listNewsEvents,
  listPapers,
  listTopics,
} from "@/lib/content";
import { pageJsonLd, pageMetadata } from "@/lib/seo";
import { NEWS } from "@/lib/site";

export const metadata: Metadata = pageMetadata(
  "最新消息",
  "大腸直腸外科與消化系臨床事件快訊，以及依本站文獻條目撰寫的新聞稿。",
  "/news/",
);

function taipeiTodayIso(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export default async function NewsIndex() {
  await connection();
  const [eventPage, news, papers, topics] = await Promise.all([
    listNewsEvents(),
    listNews(),
    listPapers(),
    listTopics(),
  ]);
  return (
    <div className="container page">
      <JsonLd
        data={pageJsonLd(
          "最新消息",
          "大腸直腸外科與消化系臨床事件快訊，以及依本站文獻條目撰寫的新聞稿。",
          "/news/",
          NEWS,
        )}
      />
      <Breadcrumb crumbs={NEWS} />
      <header className="page-head">
        <h1>最新消息</h1>
        <p className="page-head__lead">
          整理大腸直腸外科與消化系領域的監管給付、指引更新、臨床試驗快訊與文獻新聞稿；每則快訊均標註證據狀態、日期與原始來源。
        </p>
      </header>
      <div className="page__narrow">
        <Alerts />
      </div>
      <NewsFeed
        events={eventPage.items}
        news={news}
        papers={papers}
        topics={topics}
        degradedSources={eventPage.degradedSources}
        todayIso={taipeiTodayIso()}
      />
    </div>
  );
}
