import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { NewsFigure } from "@/components/news-figure";
import {
  AiChip,
  Breadcrumb,
  Icon,
  NewsCard,
  Phrases,
} from "@/components/reading";
import { getNews, listNews, listPapers, listTopics } from "@/lib/content";
import {
  doiUrl,
  headline,
  isUnreviewed,
  NEWS,
  newsPath,
  otherNews,
  paperPath,
  SOURCE_LABELS,
  topicPath,
} from "@/lib/site";

export const revalidate = 300;
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const item = await getNews((await params).id);
  return item
    ? { title: `${headline(item)}｜GutHub`, description: item.dek }
    : {};
}

export default async function NewsPage({ params }: Props) {
  const item = await getNews((await params).id);
  if (!item) notFound();
  const [papers, news, topics] = await Promise.all([
    listPapers(),
    listNews(),
    listTopics(),
  ]);
  const paper = papers.find((p) => p.id === item.paperId);
  const topicOf = (paperId: string) =>
    topics.find((t) => t.key === papers.find((p) => p.id === paperId)?.topic);
  const topic = topicOf(item.paperId);
  const others = otherNews(news, item, papers);
  const unreviewed = isUnreviewed(item);

  return (
    <article className="container page">
      <Breadcrumb crumbs={[...NEWS, [headline(item), newsPath(item)]]} />
      <div className="split">
        <div>
          <header className="story__head">
            <p className="eyebrow">
              {topic && (
                <Link className="eyebrow__topic" href={topicPath(topic)}>
                  {topic.label}
                </Link>
              )}
              <time dateTime={item.publishedAt}>{item.publishedAt}</time>
            </p>
            <h1 className="phrased">
              <Phrases item={item} />
            </h1>
            <p className="story__dek">{item.dek}</p>
            <p className="story__byline">
              <AiChip label="AI 新聞稿" />
              <span>
                依本站的文獻條目撰寫{unreviewed && "，尚未經人工審核"}
              </span>
            </p>
          </header>
          {item.figures.length > 0 && <NewsFigure item={item} />}
          <div className="story__body">
            {item.body.map((section) => (
              <section key={section.heading}>
                <h2>{section.heading}</h2>
                <p>{section.text}</p>
              </section>
            ))}
          </div>
        </div>
        <aside className="split__rail" aria-label="原始文獻與說明">
          {paper && (
            <section className="source" aria-labelledby="source-title">
              <h2 id="source-title">原始文獻</h2>
              <p className="source__title">{paper.regimen}</p>
              <p className="eyebrow">
                <span>
                  {paper.journal} {paper.year}
                </span>
                <span>{paper.studyType}</span>
                {paper.n !== null &&
                  paper.n !== undefined &&
                  paper.n !== "" && <span>n = {paper.n}</span>}
                <span>來源：{SOURCE_LABELS[paper.source]}</span>
              </p>
              <div className="source__actions">
                <Link className="btn btn--primary" href={paperPath(paper)}>
                  看文獻整理
                </Link>
                {paper.doi && (
                  <a
                    className="btn btn--secondary"
                    href={doiUrl(paper.doi)}
                    rel="noopener"
                  >
                    <Icon name="external" />
                    看原文（DOI）
                  </a>
                )}
              </div>
            </section>
          )}
          {unreviewed && (
            <div className="callout callout--ai" role="note">
              <Icon name="spark" />
              <p>
                這則新聞稿由 AI
                撰寫，尚未經人工審核。內容可能有誤，臨床判斷請以原文為準。
              </p>
            </div>
          )}
        </aside>
      </div>
      {others.length > 0 && (
        <section className="page__section" aria-labelledby="others-title">
          <h2 id="others-title">其他消息</h2>
          <ul className="news-grid">
            {others.map((other) => (
              <NewsCard
                item={other}
                topic={topicOf(other.paperId)}
                key={other.id}
              />
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
