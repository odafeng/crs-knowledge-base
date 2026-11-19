import {
  DESCRIPTION,
  pageJsonLd,
  pageMetadata,
  SITE_NAME,
  TAGLINE,
} from "@/lib/seo";
import { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { AskSite } from "@/components/ask-site";
import { FollowedUpdates } from "@/components/followed-topics";
import { NewsFigure } from "@/components/news-figure";
import {
  AiChip,
  Alerts,
  Entry,
  Icon,
  NewsCard,
  Phrases,
  Status,
  JsonLd,
} from "@/components/reading";
import { getDailyPick, listNews, listPapers, listTopics } from "@/lib/content";
import { dailyLabel } from "@/lib/daily";
import { drugCounts, drugPath } from "@/lib/drugs";
import {
  byTopic,
  isUnreviewed,
  latestCoverage,
  newsPath,
  ROBOTIC_PAGES,
  topicPath,
  updates,
  weekStats,
  HOME,
} from "@/lib/site";

const longDate = (iso: string) => {
  const [year, month, day] = iso.split("-").map(Number);
  return `${year} 年 ${month} 月 ${day} 日`;
};

export const metadata: Metadata = {
  ...pageMetadata(TAGLINE, DESCRIPTION, "/"),
  title: `${SITE_NAME}｜${TAGLINE}`,
};

// The guideline Q&A (crs-guideline-rag): a separate site that answers from the guideline text itself.
const GUIDELINE_QA = "https://crs.fredrichuang.com/";

export default async function Home() {
  // Rendered per request so `next build` never calls the API; API reads stay cached for 300 s (lib/content.ts).
  await connection();
  const [papers, news, topics, daily] = await Promise.all([
    listPapers(),
    listNews(),
    listTopics(),
    getDailyPick(),
  ]);
  const pick = daily?.pick;
  const topicOf = (paperId: string) =>
    topics.find((t) => t.key === papers.find((p) => p.id === paperId)?.topic);
  const [lead, ...rest] = news;
  const leadPaper = lead && papers.find((p) => p.id === lead.paperId);
  const leadTopic = lead && topicOf(lead.paperId);
  const stats = weekStats(papers, news);
  const mcrc = topics.filter((t) => t.roboticSections.length === 0);
  const sections = topics.flatMap((t) => t.roboticSections);

  return (
    <>
      <JsonLd data={pageJsonLd(SITE_NAME, DESCRIPTION, "/", HOME)} />
      <h1 className="visually-hidden">GutHub：大腸直腸外科實證更新</h1>
      {daily && pick && (
        <section className="daily" aria-labelledby="daily-title">
          <div className="container daily__inner">
            <h2 className="daily__label" id="daily-title">
              {dailyLabel(pick.date, daily.date)}
            </h2>
            <p className="daily__title">
              <Link href={pick.url}>{pick.title}</Link>
              {pick.unreviewed && <AiChip label="AI 未審" />}
            </p>
            <p className="daily__conclusion">{pick.conclusion}</p>
          </div>
        </section>
      )}
      <AskSite />
      {lead && (
        <section className="lead on-field" aria-labelledby="lead-title">
          <svg
            className="lead__motif"
            viewBox="0 0 800 60"
            preserveAspectRatio="none"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <path d="M0 8h120v8h90v7h140v9h110v6h150v8h190" />
            <path d="M0 8h70v14h80v12h110v10h140v8h400" />
          </svg>
          <div className="container">
            <p className="lead__dateline">
              <time dateTime={stats.lastUpdated}>
                {longDate(stats.lastUpdated)}
              </time>
              <span>
                本週新增 {stats.weekPapers} 篇文獻、{stats.weekNews} 則消息
              </span>
            </p>
            <div className="lead__grid">
              <div>
                <p className="eyebrow">
                  <span className="eyebrow__flag">頭條</span>
                  {leadTopic && (
                    <Link
                      className="eyebrow__topic"
                      href={topicPath(leadTopic)}
                    >
                      {leadTopic.label}
                    </Link>
                  )}
                  {leadPaper && (
                    <span>
                      {leadPaper.journal} {leadPaper.year}
                    </span>
                  )}
                </p>
                <h2 className="lead__headline" id="lead-title">
                  <Link href={newsPath(lead)}>
                    <Phrases item={lead} />
                  </Link>
                </h2>
                <p className="lead__dek">{lead.dek}</p>
                <div className="lead__actions">
                  <Link className="btn btn--primary" href={newsPath(lead)}>
                    讀這則消息
                    <Icon name="arrow" />
                  </Link>
                  <AiChip label="AI 新聞稿" />
                  {isUnreviewed(lead) && <AiChip label="AI 未審" />}
                </div>
              </div>
              {lead.figures.length > 0 && <NewsFigure item={lead} />}
            </div>
          </div>
        </section>
      )}
      <div className="container">
        {rest.length > 0 && (
          <section className="band" aria-labelledby="more-title">
            <div className="section-head">
              <h2 id="more-title">更多消息</h2>
              <Link href="/news/">全部消息</Link>
            </div>
            <ul className="news-grid">
              {rest.slice(0, 3).map((item) => (
                <NewsCard
                  item={item}
                  topic={topicOf(item.paperId)}
                  key={item.id}
                />
              ))}
            </ul>
          </section>
        )}
        <FollowedUpdates
          rows={updates(papers)
            .slice(0, 60)
            .map((update) => {
              const topic = topicOf(update.paper.id);
              return {
                path: `/papers/${update.paper.slug}/`,
                title: update.title,
                date: update.date,
                topic: update.paper.topic,
                topicLabel: topic?.label ?? "",
              };
            })}
        />
        <div className="band home-split">
          <section aria-labelledby="log-title">
            <div className="section-head">
              <h2 id="log-title">新收錄文獻</h2>
              <Link href="/updates/">全部 {papers.length} 篇</Link>
            </div>
            <ol className="entries">
              {updates(papers)
                .slice(0, 8)
                .map((update) => (
                  <Entry
                    update={update}
                    topic={topicOf(update.paper.id)}
                    key={update.id}
                  />
                ))}
            </ol>
          </section>
          <aside className="home-rail" aria-label="訂閱、主題、藥物與最新給付">
            <Alerts />
            <section className="ask" aria-labelledby="ask-title">
              <h2 className="rail-title" id="ask-title">
                問指引
              </h2>
              <p>
                用中文問
                NCCN、ESMO、ASCRS、JSCCR、台灣共識與健保給付規定，答案附上指引原文與出處。
              </p>
              <a
                className="btn btn--primary"
                href={GUIDELINE_QA}
                target="_blank"
                rel="noopener"
              >
                開啟指引問答
                <span className="visually-hidden">（另開新分頁）</span>
              </a>
            </section>
            <section aria-labelledby="topics-title">
              <h2 className="rail-title" id="topics-title">
                主題
              </h2>
              <ul className="topic-list">
                {mcrc.map((topic) => (
                  <li key={topic.key}>
                    <Link href={topicPath(topic)}>{topic.label}</Link>
                    <span>{byTopic(papers, topic.key).length} 篇</span>
                  </li>
                ))}
                {sections.map((section) => (
                  <li key={section.slug}>
                    <Link href={`/robotic/${section.slug}/`}>
                      {ROBOTIC_PAGES[section.slug] ?? section.slug}
                    </Link>
                    <span>{section.cards.length} 則</span>
                  </li>
                ))}
              </ul>
            </section>
            <section aria-labelledby="drugs-title">
              <h2 className="rail-title" id="drugs-title">
                藥物
              </h2>
              <ul className="topic-list">
                {drugCounts(papers)
                  .slice(0, 8)
                  .map(({ drug, count }) => (
                    <li key={drug.slug}>
                      <Link href={drugPath(drug)}>{drug.name}</Link>
                      <span>{count} 篇</span>
                    </li>
                  ))}
              </ul>
              <p className="rail-more">
                <Link href="/drugs/">全部藥物</Link>
              </p>
            </section>
            <section aria-labelledby="board-title">
              <h2 className="rail-title" id="board-title">
                最新核准給付資訊
              </h2>
              <ul className="board">
                {latestCoverage(mcrc).map((row) => (
                  <li key={`${row.topic.key}/${row.regimen}`}>
                    <Link href={topicPath(row.topic)}>{row.regimen}</Link>
                    <span className="board__states">
                      <Status regulator="nhi" value={row.nhi} prefix="健保 " />
                      <span>
                        <time dateTime={row.effective}>
                          {longDate(row.effective)}
                        </time>
                        生效
                      </span>
                    </span>
                    {row.rule ? (
                      <a className="board__rule" href={row.rule} rel="noopener">
                        給付規定 {row.clause}
                      </a>
                    ) : (
                      <span className="board__rule">給付規定 {row.clause}</span>
                    )}
                  </li>
                ))}
              </ul>
              <p className="board__note">
                日期取自健保署藥品給付規定的條文，是現行規定的生效日。
              </p>
            </section>
          </aside>
        </div>
      </div>
    </>
  );
}
