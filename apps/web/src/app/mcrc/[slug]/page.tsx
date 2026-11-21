import { pageMetadata, pageJsonLd } from "@/lib/seo";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  Breadcrumb,
  NewsCard,
  PaperCard,
  RichHtml,
  Status,
  JsonLd,
} from "@/components/reading";
import { ScrollTable } from "@/components/scroll-table";
import { getTopicBySlug, listNews, listPapers } from "@/lib/content";
import {
  byTopic,
  MCRC,
  regulatoryRows,
  repairCardHtml,
  topicPath,
} from "@/lib/site";
import { boardPath } from "@/lib/tumor-board";

export const revalidate = 300;
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const topic = await getTopicBySlug((await params).slug);
  return topic
    ? pageMetadata(
        topic.label,
        `${topic.title}的試驗實證，共 ${topic.paperCount} 篇。`,
        topicPath(topic),
      )
    : {};
}

export default async function TopicPage({ params }: Props) {
  const topic = await getTopicBySlug((await params).slug);
  // The robotic topic has its own section pages under /robotic/.
  if (!topic || topic.roboticSections.length > 0) notFound();
  const [allPapers, news] = await Promise.all([listPapers(), listNews()]);
  const papers = byTopic(allPapers, topic.key);
  const ids = new Set(papers.map((p) => p.id));
  const stories = news.filter((item) => ids.has(item.paperId)).slice(0, 3);
  const regulatory = regulatoryRows(topic);
  const crumbs = [...MCRC, [topic.label, topicPath(topic)] as const];

  return (
    <div className="container page">
      <JsonLd
        data={pageJsonLd(
          topic.label,
          `${topic.title}的試驗實證，共 ${papers.length} 篇。`,
          topicPath(topic),
          crumbs,
        )}
      />
      <Breadcrumb crumbs={crumbs} />
      <header className="page-head">
        <h1>{topic.title}</h1>
        <p className="page-head__lead">共 {papers.length} 篇文獻。</p>
        <div className="page-head__bar">
          {topic.standardOfCare.length > 0 && (
            <div className="page-head__actions">
              <Link className="btn btn--secondary" href={boardPath(topic)}>
                Tumor board 一頁摘要
              </Link>
            </div>
          )}
          <nav className="section-nav" aria-label="本頁章節">
            {regulatory.length > 0 && <a href="#reg">核准與給付現況</a>}
            {topic.standardOfCare.length > 0 && <a href="#soc">治療現況</a>}
            <a href="#papers">文獻（{papers.length}）</a>
          </nav>
        </div>
      </header>
      {stories.length > 0 && (
        <section aria-labelledby="stories">
          <h2 className="visually-hidden" id="stories">
            這個主題的消息
          </h2>
          <ul className="news-grid">
            {stories.map((item) => (
              <NewsCard item={item} topic={topic} key={item.id} />
            ))}
          </ul>
        </section>
      )}
      {regulatory.length > 0 && (
        <section className="page__section" aria-labelledby="reg">
          <h2 id="reg">核准與給付現況</h2>
          <ScrollTable
            label="核准與給付現況表格，可左右捲動"
            hint="左右滑動查看 TFDA、健保與查核日"
          >
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">方案</th>
                  <th scope="col">FDA</th>
                  <th scope="col">TFDA</th>
                  <th scope="col">健保</th>
                  <th scope="col">查核日</th>
                </tr>
              </thead>
              <tbody>
                {regulatory.map((row) => (
                  <tr key={row.regimen}>
                    <td>
                      {row.regimen}
                      {row.note && <span className="note">{row.note}</span>}
                    </td>
                    <td>
                      <Status regulator="fda" value={row.fda} />
                    </td>
                    <td>
                      <Status regulator="tfda" value={row.tfda} />
                    </td>
                    <td>
                      <Status regulator="nhi" value={row.nhi} />
                    </td>
                    <td>{row.checkedAt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        </section>
      )}
      {topic.standardOfCare.length > 0 && (
        <section className="page__section" aria-labelledby="soc">
          <h2 id="soc">治療現況</h2>
          {topic.standardOfCare.map((card, index) => (
            <details className="accordion" open={index === 0} key={card.title}>
              <summary>{card.title}</summary>
              <RichHtml
                html={repairCardHtml(card.body_html)}
                label={card.title}
                role="group"
              />
              <p className="note">最近複查 {card.reviewedAt}</p>
            </details>
          ))}
        </section>
      )}
      <section className="page__section" aria-labelledby="papers">
        <h2 id="papers">文獻</h2>
        <ul className="paper-list">
          {papers.map((paper) => (
            <PaperCard paper={paper} key={paper.id} />
          ))}
        </ul>
      </section>
    </div>
  );
}
