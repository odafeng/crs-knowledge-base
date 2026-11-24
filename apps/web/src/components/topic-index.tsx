// The topic index pages (templates/topics.html.j2): /topics/ shows both groups, /mcrc/ and /robotic/ one each.
import Link from "next/link";
import { Breadcrumb, PaperCard } from "@/components/reading";
import { listPapers, listTopics } from "@/lib/content";
import { byTopic, ROBOTIC_PAGES, topicPath, type Crumbs } from "@/lib/site";

type Group = "mcrc" | "robotic";
const GROUPS: Record<Group, readonly [name: string, href: string]> = {
  mcrc: ["mCRC 治療", "/mcrc/"],
  robotic: ["機器手臂手術", "/robotic/"],
};

export async function TopicIndex({
  crumbs,
  groups,
}: {
  crumbs: Crumbs;
  groups: readonly Group[];
}) {
  const [topics, papers] = await Promise.all([listTopics(), listPapers()]);
  const heading = crumbs[crumbs.length - 1][0];
  const mcrc = topics.filter((t) => t.roboticSections.length === 0);
  const roboticTopic = topics.find((t) => t.roboticSections.length > 0);
  const sections = topics.flatMap((t) => t.roboticSections);
  const roboticPapers = roboticTopic ? byTopic(papers, roboticTopic.key) : [];
  return (
    <div className="container page">
      <Breadcrumb crumbs={crumbs} />
      <header className="page-head">
        <h1>{heading}</h1>
        <p className="page-head__lead">
          {groups.length === 1 && groups[0] === "robotic"
            ? "機器手臂 TME、吻合技術與微創大腸直腸外科試驗實證。"
            : "每個主題有核准與給付現況、治療現況與全部文獻。"}
        </p>
      </header>
      {groups.map((group) => (
        <section
          className="page__section"
          aria-labelledby={`group-${group}`}
          key={group}
        >
          <h2 id={`group-${group}`}>
            {groups.length > 1 ? (
              <Link href={GROUPS[group][1]}>{GROUPS[group][0]}</Link>
            ) : group === "robotic" ? (
              "實證總覽"
            ) : (
              "主題"
            )}
          </h2>
          <ul className="tile-grid">
            {group === "mcrc" ? (
              mcrc.map((topic) => {
                const mine = byTopic(papers, topic.key);
                return (
                  <li className="tile" key={topic.key}>
                    <p className="tile__count">
                      <span className="num">{mine.length}</span>篇文獻
                    </p>
                    <h3 className="tile__title">
                      <Link href={topicPath(topic)}>{topic.label}</Link>
                    </h3>
                    {mine[0] && (
                      <p className="tile__text">
                        最新：{mine[0].regimen}（{mine[0].journal}{" "}
                        {mine[0].year}）
                      </p>
                    )}
                  </li>
                );
              })
            ) : (
              <>
                {sections.map((section) => (
                  <li className="tile" key={section.slug}>
                    <p className="tile__count">
                      <span className="num">{section.cards.length}</span>
                      則實證整理
                    </p>
                    <h3 className="tile__title">
                      <Link href={`/robotic/${section.slug}/`}>
                        {ROBOTIC_PAGES[section.slug] ?? section.slug}
                      </Link>
                    </h3>
                    <p className="tile__text">
                      證據演進有 {section.timeline.length} 個時間點
                    </p>
                  </li>
                ))}
                {groups.length > 1 && roboticPapers.length > 0 && (
                  <li className="tile" key="robotic-papers">
                    <p className="tile__count">
                      <span className="num">{roboticPapers.length}</span>篇文獻
                    </p>
                    <h3 className="tile__title">
                      <Link href="/robotic/#robotic-papers">
                        最新收錄外科文獻
                      </Link>
                    </h3>
                    <p className="tile__text">
                      最新：{roboticPapers[0].regimen}（
                      {roboticPapers[0].journal} {roboticPapers[0].year}）
                    </p>
                  </li>
                )}
              </>
            )}
          </ul>
        </section>
      ))}
      {groups.length === 1 &&
        groups[0] === "robotic" &&
        roboticPapers.length > 0 && (
          <section className="page__section" aria-labelledby="robotic-papers">
            <h2 id="robotic-papers">
              最新收錄外科文獻（{roboticPapers.length} 篇）
            </h2>
            <ul className="paper-list">
              {roboticPapers.map((paper) => (
                <PaperCard paper={paper} key={paper.id} />
              ))}
            </ul>
          </section>
        )}
      {groups.length > 1 && (
        <section className="page__section" aria-labelledby="group-drugs">
          <h2 id="group-drugs">
            <Link href="/drugs/">藥物索引</Link>
          </h2>
          <p className="page-head__lead">
            改依藥物名稱瀏覽所有試驗與實證演進時間軸。{" "}
            <Link href="/drugs/">前往全部藥物</Link>
          </p>
        </section>
      )}
    </div>
  );
}
