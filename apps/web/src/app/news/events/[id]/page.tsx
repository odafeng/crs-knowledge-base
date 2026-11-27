import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AiChip, Breadcrumb, Icon, JsonLd } from "@/components/reading";
import styles from "@/components/news-feed.module.css";
import { getNewsEvent } from "@/lib/content";
import { newsEventJsonLd, pageMetadata } from "@/lib/seo";
import {
  domainBySlug,
  EVENT_CATEGORY_LABELS,
  EVENT_EVIDENCE_LABELS,
  EVENT_GEOGRAPHY_LABELS,
  EVENT_REVIEW_LABELS,
  isUnreviewedEvent,
  NEWS,
  newsEventPath,
  specialtyPath,
} from "@/lib/site";

export const revalidate = 3600;
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const event = await getNewsEvent((await params).id);
  return event
    ? pageMetadata(event.headline, event.whatHappened, newsEventPath(event), {
        indexable: !isUnreviewedEvent(event),
        type: "article",
      })
    : {};
}

export default async function NewsEventPage({ params }: Props) {
  const event = await getNewsEvent((await params).id);
  if (!event) notFound();

  const primary = event.primaryDomain
    ? domainBySlug(event.primaryDomain)
    : undefined;
  const secondaries = event.secondaryDomains
    .map((slug) => domainBySlug(slug))
    .filter((d): d is NonNullable<typeof d> => d !== undefined);
  const unreviewed = isUnreviewedEvent(event);
  const crumbs = [...NEWS, [event.headline, newsEventPath(event)] as const];

  const reviewBadgeClass =
    event.reviewStatus === "reviewed"
      ? `${styles.badge} ${styles.badgeReviewed}`
      : event.reviewStatus === "revised"
        ? `${styles.badge} ${styles.badgeRevised}`
        : "";

  return (
    <article className="container page">
      <JsonLd data={newsEventJsonLd(event, crumbs)} />
      <Breadcrumb crumbs={crumbs} />
      <div className="split">
        <div>
          <header className="story__head">
            <p className="eyebrow">
              {primary && (
                <Link
                  className="eyebrow__topic"
                  href={specialtyPath(primary.slug)}
                >
                  {primary.labelZh}
                </Link>
              )}
              {secondaries.map((sec) => (
                <Link key={sec.slug} href={specialtyPath(sec.slug)}>
                  {sec.labelZh}
                </Link>
              ))}
              <span>{EVENT_CATEGORY_LABELS[event.category]}</span>
              <span>{EVENT_GEOGRAPHY_LABELS[event.geography]}</span>
              <time dateTime={event.publishedAt}>{event.publishedAt}</time>
            </p>
            <h1>{event.headline}</h1>
            <p className="story__byline">
              {unreviewed ? (
                <AiChip label={EVENT_REVIEW_LABELS.auto} />
              ) : (
                <span className={reviewBadgeClass}>
                  {EVENT_REVIEW_LABELS[event.reviewStatus]}
                </span>
              )}
              <span className={styles.badge}>
                {EVENT_EVIDENCE_LABELS[event.evidenceStatus]}
              </span>
              <span>修訂版本 v{event.revisionNumber}</span>
            </p>
          </header>

          {event.correctionNote && (
            <div className="callout" role="note">
              <Icon name="info" />
              <p>
                <strong>更正與修訂說明：</strong>
                {event.correctionNote}
              </p>
            </div>
          )}

          <div className="story__body">
            <section aria-labelledby="sec-what">
              <h2 id="sec-what">發生了什麼</h2>
              <p>{event.whatHappened}</p>
            </section>
            <section aria-labelledby="sec-why">
              <h2 id="sec-why">為什麼重要</h2>
              <p>{event.whyItMatters}</p>
            </section>
            <section aria-labelledby="sec-clinical">
              <h2 id="sec-clinical">臨床關聯</h2>
              <p>{event.clinicalRelevance}</p>
            </section>
            <section aria-labelledby="sec-limits">
              <h2 id="sec-limits">證據狀態與限制</h2>
              <p>{event.evidenceLimitations}</p>
            </section>
          </div>
        </div>

        <aside className="split__rail" aria-label="事件日期與原始來源">
          <dl className="facts" aria-label="事件摘要資訊">
            <dt>發布日期</dt>
            <dd>
              <time dateTime={event.publishedAt}>{event.publishedAt}</time>
            </dd>
            {event.eventDate && (
              <>
                <dt>事件日期</dt>
                <dd>
                  <time dateTime={event.eventDate}>{event.eventDate}</time>
                </dd>
              </>
            )}
            {event.effectiveDate && (
              <>
                <dt>生效日期</dt>
                <dd>
                  <time dateTime={event.effectiveDate}>
                    {event.effectiveDate}
                  </time>
                </dd>
              </>
            )}
            <dt>證據狀態</dt>
            <dd>{EVENT_EVIDENCE_LABELS[event.evidenceStatus]}</dd>
            <dt>審核狀態</dt>
            <dd>{EVENT_REVIEW_LABELS[event.reviewStatus]}</dd>
            <dt>版本</dt>
            <dd>v{event.revisionNumber}</dd>
          </dl>

          {event.sources.length > 0 && (
            <section className="source" aria-labelledby="event-sources-title">
              <h2 id="event-sources-title">原始來源</h2>
              <ul className={styles.sourcesList}>
                {event.sources.map((src) => (
                  <li className={styles.sourceItem} key={src.url}>
                    <a
                      className={styles.sourceLink}
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <Icon name="external" />
                      <span>{src.title}</span>
                    </a>
                    <span className={styles.sourceMeta}>
                      {src.publisher}
                      {src.publishedAt ? ` · ${src.publishedAt}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {unreviewed && (
            <div className="callout callout--ai" role="note">
              <Icon name="info" />
              <p>
                這則事件快訊由 AI
                依原始來源草擬，尚未經人工審核。臨床判斷與法規適用請以原始公告或文獻為準。
              </p>
            </div>
          )}
        </aside>
      </div>
    </article>
  );
}
