import type { Metadata } from "next";
import { pageJsonLd, pageMetadata } from "@/lib/seo";
import { connection } from "next/server";
import { Alerts, Breadcrumb, JsonLd } from "@/components/reading";
import { listNews, listPapers, listTopics } from "@/lib/content";
import { pushEnabled } from "@/lib/push";
import { feedList, HOME } from "@/lib/site";

export const metadata: Metadata = pageMetadata(
  "訂閱",
  "用推播或 RSS 接收新消息，或只訂閱關心的主題。",
  "/subscribe/",
);

export default async function SubscribePage() {
  await connection();
  const [papers, news, topics] = await Promise.all([
    listPapers(),
    listNews(),
    listTopics(),
  ]);
  const feeds = [
    ...feedList(papers, news, topics).map((feed) => ({
      ...feed,
      format: "RSS",
    })),
    { label: "全部更新", path: "/atom.xml", format: "Atom" },
    { label: "全部更新", path: "/feed.json", format: "JSON Feed" },
  ];
  return (
    <div className="container page">
      <JsonLd
        data={pageJsonLd(
          "訂閱",
          "用推播或 RSS 接收新消息，或只訂閱關心的主題。",
          "/subscribe/",
          [...HOME, ["訂閱", "/subscribe/"]],
        )}
      />
      <Breadcrumb crumbs={[...HOME, ["訂閱", "/subscribe/"]]} />
      <header className="page-head">
        <h1>訂閱</h1>
        <p className="page-head__lead">
          {pushEnabled
            ? "開啟推播，或用 RSS 訂閱全部更新、只訂閱關心的主題。不需要留 Email。"
            : "用 RSS 訂閱全部更新，或只訂閱關心的主題。不需要留 Email。"}
        </p>
      </header>
      <div className="page__narrow">
        <Alerts />
        <div className="prose page__section">
          <h2>用 RSS 訂閱</h2>
          <ol>
            <li>
              選一個閱讀器：Feedly 或 Inoreader（網頁與手機都能用），或
              NetNewsWire（iPhone、iPad、Mac）。
            </li>
            <li>複製下表的訂閱網址。</li>
            <li>在閱讀器選「新增訂閱」，貼上網址。</li>
          </ol>
        </div>
      </div>
      <div
        className="table-wrap page__section"
        tabIndex={0}
        role="region"
        aria-label="訂閱網址表格，可左右捲動"
      >
        <table className="table">
          <thead>
            <tr>
              <th scope="col">內容</th>
              <th scope="col">格式</th>
              <th scope="col">網址</th>
            </tr>
          </thead>
          <tbody>
            {feeds.map((feed) => (
              <tr key={feed.path}>
                <td>{feed.label}</td>
                <td>{feed.format}</td>
                {/* Absolute addresses for copying come with C2c (#92), which fixes the canonical origin. */}
                <td>
                  <a href={feed.path}>{feed.path}</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
