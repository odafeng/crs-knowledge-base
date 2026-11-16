import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { listTopics } from "@/lib/content";
import { pageMetadata } from "@/lib/seo";
import { boardPath, boardTopics } from "@/lib/tumor-board";

export const metadata: Metadata = pageMetadata(
  "Tumor board 摘要",
  "依分子型別整理的一頁摘要：治療現況、台灣核准與給付、關鍵試驗，可直接列印。",
  "/tumor-board/",
  { indexable: false },
);

export default async function TumorBoardIndex() {
  await connection();
  const topics = boardTopics(await listTopics());
  return (
    <div className="container page">
      <header className="page-head">
        <h1>Tumor board 摘要</h1>
        <p className="page-head__lead">
          選一個分子型別，取得一頁可列印的摘要：治療現況、台灣核准與給付狀態，以及卡片引用的關鍵試驗。
        </p>
      </header>
      <ul className="tile-grid">
        {topics.map((topic) => (
          <li className="tile" key={topic.key}>
            <h2 className="tile__title">
              <Link href={boardPath(topic)}>{topic.title}</Link>
            </h2>
          </li>
        ))}
      </ul>
    </div>
  );
}
