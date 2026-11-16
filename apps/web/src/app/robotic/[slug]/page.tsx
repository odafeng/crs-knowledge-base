import { pageMetadata, pageJsonLd } from "@/lib/seo";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Breadcrumb, RichHtml, JsonLd } from "@/components/reading";
import { listTopics } from "@/lib/content";
import {
  findingText,
  repairCardHtml,
  ROBOTIC,
  ROBOTIC_PAGES,
} from "@/lib/site";

export const revalidate = 300;
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ slug: string }> };

async function getSection(slug: string) {
  const title = ROBOTIC_PAGES[slug];
  if (!title) return null;
  const section = (await listTopics())
    .flatMap((t) => t.roboticSections)
    .find((s) => s.slug === slug);
  return section ? { title, section } : null;
}

/** The current site shows a finding as plain text with line breaks turned into "，" (templates/robotic.html.j2). */
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const found = await getSection((await params).slug);
  return found
    ? pageMetadata(
        found.title,
        `${found.title}的試驗實證。`,
        `/robotic/${found.section.slug}/`,
      )
    : {};
}

export default async function RoboticPage({ params }: Props) {
  const found = await getSection((await params).slug);
  if (!found) notFound();
  const { title, section } = found;
  const crumbs = [...ROBOTIC, [title, `/robotic/${section.slug}/`] as const];

  return (
    <div className="container page">
      <JsonLd
        data={pageJsonLd(
          title,
          `${title}的試驗實證。`,
          `/robotic/${section.slug}/`,
          crumbs,
        )}
      />
      <Breadcrumb crumbs={crumbs} />
      <header className="page-head">
        <h1>{title}</h1>
        <p className="page-head__lead">
          {section.cards.length} 則實證整理，證據演進有{" "}
          {section.timeline.length} 個時間點。
        </p>
      </header>
      <section aria-labelledby="tl">
        <h2 className="rail-title" id="tl">
          證據演進
        </h2>
        <ol className="timeline">
          {section.timeline.map((t, index) => (
            <li key={index}>
              <span className="timeline__when">
                {t.yr} · {t.venue}
              </span>
              <span className="timeline__what">{findingText(t.finding)}</span>
              {t.file?.startsWith("http") && (
                <a href={t.file} rel="noopener">
                  原文
                </a>
              )}
            </li>
          ))}
        </ol>
      </section>
      <section className="page__section" aria-labelledby="cards">
        <h2 id="cards">實證整理</h2>
        {section.cards.map((card, index) => (
          <details className="accordion" open={index === 0} key={card.title}>
            <summary>{card.title}</summary>
            <RichHtml
              html={repairCardHtml(card.body)}
              label={card.title}
              role="group"
            />
          </details>
        ))}
      </section>
      {section.detailHtml.length > 0 && (
        <section className="page__section" aria-labelledby="details">
          <h2 id="details">詳細證據整理</h2>
          {section.detailHtml.map((html, index) => (
            <RichHtml
              html={html}
              label={`詳細證據整理 ${index + 1}，可左右捲動`}
              key={index}
            />
          ))}
        </section>
      )}
    </div>
  );
}
