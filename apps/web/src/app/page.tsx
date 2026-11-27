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
import { RecentNewsTicker } from "@/components/recent-news-ticker";
import { TopicMap } from "@/components/topic-map";
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
import {
  getDailyPick,
  listNews,
  listNewsEvents,
  listPapers,
  listTopics,
} from "@/lib/content";
import { buildRecentTicker } from "@/lib/daily";
import { drugCounts, drugPath } from "@/lib/drugs";
import {
  byDomain,
  byTopic,
  domainsOfPaper,
  formatWeekSummary,
  isUnreviewed,
  latestCoverage,
  newsPath,
  paperPath,
  plateKicker,
  ROBOTIC_PAGES,
  specialtyPath,
  topicPath,
  updates,
  weekStats,
  HOME,
} from "@/lib/site";
import { TAXONOMY_DOMAINS } from "@/lib/taxonomy.generated";

const longDate = (iso: string) => {
  const [year, month, day] = iso.split("-").map(Number);
  return `${year} 年 ${month} 月 ${day} 日`;
};

export const metadata: Metadata = {
  ...pageMetadata(TAGLINE, DESCRIPTION, "/"),
  title: `${SITE_NAME}｜${TAGLINE}`,
};

export default async function Home() {
  // Rendered per request so `next build` never calls the API; API reads stay cached for 300 s (lib/content.ts).
  await connection();
  const [papers, news, topics, daily, eventPage] = await Promise.all([
    listPapers(),
    listNews(),
    listTopics(),
    getDailyPick(),
    listNewsEvents(),
  ]);
  const events = eventPage.items;
  const pick = daily?.pick;
  const topicOf = (paperId: string) =>
    topics.find((t) => t.key === papers.find((p) => p.id === paperId)?.topic);
  const [lead, ...rest] = news;
  const leadPaper = lead && papers.find((p) => p.id === lead.paperId);
  const leadTopic = lead && topicOf(lead.paperId);
  const stats = weekStats(papers, news, events);
  const mcrc = topics.filter((t) => t.roboticSections.length === 0);
  const sections = topics.flatMap((t) => t.roboticSections);
  const allUpdates = updates(papers);
  // Avoid repeating the daily pick verbatim as the first row of "新收錄文獻" right below.
  const recentUpdates =
    pick && allUpdates.length > 1
      ? allUpdates.filter(
          (u) => !(u.kind === "paper" && paperPath(u.paper) === pick.url),
        )
      : allUpdates;
  const allDrugs = drugCounts(papers);
  const topDrugs = allDrugs.slice(0, 12);
  const tickerItems = buildRecentTicker(news, papers, topics, daily, 5, events);

  return (
    <>
      <JsonLd data={pageJsonLd(SITE_NAME, DESCRIPTION, "/", HOME)} />
      <h1 className="visually-hidden">GutHub：大腸直腸外科實證更新</h1>
      <RecentNewsTicker items={tickerItems} />
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
              <span>{formatWeekSummary(stats)}</span>
            </p>
            <div
              className={
                lead.figures.length > 0
                  ? "lead__grid"
                  : "lead__grid lead__grid--plate"
              }
            >
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
                  <time dateTime={lead.publishedAt}>{lead.publishedAt}</time>
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
              {lead.figures.length > 0 ? (
                <NewsFigure item={lead} />
              ) : (
                <div className="lead__plate">
                  <span className="lead__plate-kicker">
                    {plateKicker(lead.key.value)}
                  </span>
                  <p className="lead__plate-value num">
                    {lead.key.value}
                    {lead.key.unit && (
                      <span className="stat__unit">{lead.key.unit}</span>
                    )}
                  </p>
                  <p className="lead__plate-label">{lead.key.label}</p>
                </div>
              )}
            </div>
          </div>
        </section>
      )}
      <AskSite />
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
          rows={allUpdates.slice(0, 60).map((update) => {
            const topic = topicOf(update.paper.id);
            return {
              path: `/papers/${update.paper.slug}/`,
              title: update.title,
              date: update.date,
              topic: update.paper.topic,
              topicLabel: topic?.label ?? "",
              domains: domainsOfPaper(update.paper),
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
              {recentUpdates.slice(0, 6).map((update) => (
                <Entry
                  update={update}
                  topic={topicOf(update.paper.id)}
                  key={update.id}
                />
              ))}
            </ol>
            <p className="page__more">
              <Link href="/updates/">
                瀏覽全部 {papers.length} 篇文獻與評論
              </Link>
            </p>
          </section>
          <aside className="home-rail" aria-label="訂閱、主題、最新給付與藥物">
            <Alerts />
            <section className="rail-section" aria-labelledby="topics-title">
              <div className="rail-head">
                <h2 className="rail-title" id="topics-title">
                  依專科瀏覽
                </h2>
                <Link href="/topics/">全部主題</Link>
              </div>
              <TopicMap
                label="八大專科"
                unit="篇"
                rows={TAXONOMY_DOMAINS.map((domain) => ({
                  key: domain.slug,
                  href: specialtyPath(domain.slug),
                  name: domain.labelZh,
                  count: byDomain(papers, domain.slug).length,
                }))}
              />
              <TopicMap
                label="mCRC 治療"
                unit="篇"
                rows={mcrc.map((topic) => ({
                  key: topic.key,
                  href: topicPath(topic),
                  name: topic.label,
                  count: byTopic(papers, topic.key).length,
                }))}
              />
              <TopicMap
                label="機器手臂手術"
                unit="則"
                rows={sections.map((section) => ({
                  key: section.slug,
                  href: `/robotic/${section.slug}/`,
                  name: ROBOTIC_PAGES[section.slug] ?? section.slug,
                  count: section.cards.length,
                }))}
              />
            </section>
            <section className="rail-section" aria-labelledby="board-title">
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
            {topDrugs.length > 0 && (
              <section className="rail-section" aria-labelledby="drugs-title">
                <div className="rail-head">
                  <h2 className="rail-title" id="drugs-title">
                    常用藥物
                  </h2>
                  <Link href="/drugs/">全部 {allDrugs.length} 種</Link>
                </div>
                <ul className="drug-chips">
                  {topDrugs.map(({ drug, count }) => (
                    <li key={drug.slug}>
                      <Link className="drug-chip" href={drugPath(drug)}>
                        {drug.name}
                        <span className="drug-chip__count">
                          {count}
                          <span className="visually-hidden"> 篇</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </aside>
        </div>
      </div>
    </>
  );
}
