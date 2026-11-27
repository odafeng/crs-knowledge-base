import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Breadcrumb, JsonLd, NewsCard, PaperCard } from "@/components/reading";
import { getDomain, listNews, listPapers, listTopics } from "@/lib/content";
import { pageJsonLd, pageMetadata } from "@/lib/seo";
import { byDomain, byTopic, specialtyPath, TOPICS } from "@/lib/site";

export const revalidate = 3600;
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ domain: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const domain = await getDomain((await params).domain);
  return domain
    ? pageMetadata(
        domain.labelZh,
        domain.descriptionZh,
        specialtyPath(domain.slug),
      )
    : {};
}

export default async function SpecialtyPage({ params }: Props) {
  const domain = await getDomain((await params).domain);
  if (!domain) notFound();

  const [allPapers, news, topics] = await Promise.all([
    listPapers(),
    listNews(),
    listTopics(),
  ]);
  const papers = byDomain(allPapers, domain.slug);
  const paperIds = new Set(papers.map((p) => p.id));
  const stories = news.filter((item) => paperIds.has(item.paperId)).slice(0, 3);
  const topicByKey = new Map<string, (typeof topics)[number]>(
    topics.map((t) => [t.key, t]),
  );
  const topicOf = (paperId: string) =>
    topicByKey.get(allPapers.find((p) => p.id === paperId)?.topic ?? "");

  const linkedSubtopics = domain.subtopics.filter((s) => Boolean(s.routePath));
  const scopeSubtopics = domain.subtopics.filter((s) => !s.routePath);
  const crumbs = [
    ...TOPICS,
    [domain.labelZh, specialtyPath(domain.slug)] as const,
  ];

  return (
    <div className="container page">
      <JsonLd
        data={pageJsonLd(
          domain.labelZh,
          domain.descriptionZh,
          specialtyPath(domain.slug),
          crumbs,
        )}
      />
      <Breadcrumb crumbs={crumbs} />
      <header className="page-head">
        <h1>{domain.labelZh}</h1>
        <p className="page-head__lead">{domain.descriptionZh}</p>
        <p className="note">
          {domain.labelEn}
          {papers.length > 0
            ? ` · 目前收錄 ${papers.length} 篇文獻`
            : " · 此專科文獻追蹤建置中"}
        </p>
      </header>

      {linkedSubtopics.length > 0 && (
        <section
          className="page__section"
          aria-labelledby="specialty-subtopics"
        >
          <h2 id="specialty-subtopics">深層專題整理</h2>
          <ul className="tile-grid">
            {linkedSubtopics.map((sub) => {
              const legacyTopic = sub.legacyTopicKey
                ? topicByKey.get(sub.legacyTopicKey)
                : undefined;
              const count = legacyTopic
                ? byTopic(allPapers, legacyTopic.key).length
                : 0;
              return (
                <li className="tile" key={sub.id}>
                  <p className="tile__count">
                    {legacyTopic && legacyTopic.roboticSections.length > 0 ? (
                      <>
                        <span className="num">
                          {legacyTopic.roboticSections.reduce(
                            (sum, sec) => sum + sec.cards.length,
                            0,
                          )}
                        </span>
                        則實證整理
                      </>
                    ) : (
                      <>
                        <span className="num">{count}</span>篇文獻
                      </>
                    )}
                  </p>
                  <h3 className="tile__title">
                    <Link href={sub.routePath!}>{sub.labelZh}</Link>
                  </h3>
                  <p className="tile__text">{sub.labelEn}</p>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {scopeSubtopics.length > 0 && (
        <section className="page__section" aria-labelledby="specialty-scope">
          <h2 id="specialty-scope">涵蓋次領域</h2>
          <ul className="drug-chips">
            {scopeSubtopics.map((sub) => (
              <li key={sub.id}>
                <span className="chip">{sub.labelZh}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {stories.length > 0 && (
        <section className="page__section" aria-labelledby="specialty-news">
          <h2 id="specialty-news">相關最新消息</h2>
          <ul className="news-grid">
            {stories.map((item) => (
              <NewsCard
                item={item}
                topic={topicOf(item.paperId)}
                key={item.id}
              />
            ))}
          </ul>
        </section>
      )}

      <section className="page__section" aria-labelledby="specialty-papers">
        <h2 id="specialty-papers">
          收錄文獻{papers.length > 0 ? `（${papers.length} 篇）` : ""}
        </h2>
        {papers.length > 0 ? (
          <ul className="paper-list">
            {papers.map((paper) => (
              <PaperCard paper={paper} key={paper.id} />
            ))}
          </ul>
        ) : (
          <div className="empty-state">
            <p>
              「{domain.labelZh}」目前已納入 GutHub
              八大專科架構，相關文獻與每日情報將依分批驗證排程陸續收錄。
            </p>
            <div className="comment__actions">
              <Link className="btn btn--secondary" href="/topics/">
                瀏覽全部專科與主題
              </Link>
              <Link className="btn btn--quiet" href="/updates/">
                查看最新收錄文獻
              </Link>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
