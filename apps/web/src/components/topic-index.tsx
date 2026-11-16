// The topic index pages (templates/topics.html.j2): /topics/ shows both groups, /mcrc/ and /robotic/ one each.
import Link from "next/link";
import { Breadcrumb } from "@/components/reading";
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
  const sections = topics.flatMap((t) => t.roboticSections);
  return (
    <div className="container page">
      <Breadcrumb crumbs={crumbs} />
      <header className="page-head">
        <h1>{heading}</h1>
        <p className="page-head__lead">
          每個主題有核准與給付現況、治療現況與全部文獻。
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
            ) : (
              "主題"
            )}
          </h2>
          <ul className="tile-grid">
            {group === "mcrc"
              ? mcrc.map((topic) => {
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
              : sections.map((section) => (
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
          </ul>
        </section>
      ))}
    </div>
  );
}
