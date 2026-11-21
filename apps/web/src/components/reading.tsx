// Building blocks of the reading pages, ported from templates/_macros.html.j2.
import Link from "next/link";
import { PushToggle } from "@/components/push-toggle";
import { pushEnabled } from "@/lib/push";
import {
  headline,
  isUnreviewed,
  newsPath,
  paperLead,
  paperPath,
  SOURCE_LABELS,
  STATUS_LABELS,
  STATUS_STYLE,
  topicPath,
  NEWS_FEED,
  type Crumbs,
  type Update,
  type News,
  type Paper,
  type Topic,
} from "@/lib/site";

// Inline SVG paths from sitegen/icons.py (24x24, stroke); constant strings, never user content.
const ICONS = {
  home: '<path d="m4 11 8-7 8 7"/><path d="M6 10v9h12v-9"/>',
  list: '<path d="M9 7h10M9 12h10M9 17h10"/><path d="M5 7h.01M5 12h.01M5 17h.01"/>',
  grid: '<rect x="4.5" y="4.5" width="6" height="6" rx="1.5"/><rect x="13.5" y="4.5" width="6" height="6" rx="1.5"/><rect x="4.5" y="13.5" width="6" height="6" rx="1.5"/><rect x="13.5" y="13.5" width="6" height="6" rx="1.5"/>',
  bell: '<path d="M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  theme: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  account: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  rss: '<path d="M5 11a8 8 0 0 1 8 8M5 5a14 14 0 0 1 14 14"/><circle cx="6" cy="18" r="1.25"/>',
  news: '<path d="M5 5h11v14H7a2 2 0 0 1-2-2z"/><path d="M16 9h3v8a2 2 0 0 1-2 2"/><path d="M8 9h5M8 12.5h5M8 16h3"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2"/>',
  x: '<path d="m7 7 10 10M17 7 7 17"/>',
  question:
    '<path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7"/><path d="M12 17h.01"/>',
  spark:
    '<path d="m12 4 1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z"/><path d="M18.5 15.5v3M17 17h3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 10.5v5.5"/><circle cx="12" cy="7.5" r=".6" fill="currentColor"/>',
  chat: '<path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v6.5a2.5 2.5 0 0 1-2.5 2.5H11l-4.2 3.5V15.5H7.5A2.5 2.5 0 0 1 5 13z"/>',
  external:
    '<path d="M14 5h5v5M19 5l-8 8"/><path d="M11 6H6a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-5"/>',
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: ICONS[name] }}
    />
  );
}

/** HTML the API has sanitized with its allowlist (B5). */
export function RichHtml({
  html,
  label,
  role = "region",
}: {
  html: string;
  label: string;
  role?: "region" | "group";
}) {
  return (
    <div
      className="richtext"
      tabIndex={0}
      role={role}
      aria-label={label}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export function Breadcrumb({ crumbs }: { crumbs: Crumbs }) {
  return (
    <nav className="breadcrumb" aria-label="麵包屑">
      <ol>
        {crumbs.map(([name, path], index) =>
          index === crumbs.length - 1 ? (
            <li key={path} aria-current="page">
              {name}
            </li>
          ) : (
            <li key={path}>
              <Link href={path}>{name}</Link>
            </li>
          ),
        )}
      </ol>
    </nav>
  );
}

export function AiChip({ label }: { label: string }) {
  return <span className="chip chip--ai">{label}</span>;
}

export function Status({
  regulator,
  value,
  prefix = "",
}: {
  regulator: keyof typeof STATUS_LABELS;
  value: string;
  prefix?: string;
}) {
  const [style, glyph] = STATUS_STYLE[value] ?? STATUS_STYLE.unknown;
  const labels: Record<string, string> = STATUS_LABELS[regulator];
  return (
    <span className={`status status--${style}`}>
      <Icon name={glyph as IconName} />
      {prefix}
      {labels[value] ?? value}
    </span>
  );
}

/** The line above a paper: where it belongs and what kind of evidence it is. */
export function PaperMeta({
  paper,
  topic,
  when,
}: {
  paper: Paper;
  topic?: Topic;
  when?: string;
}) {
  return (
    <p className="eyebrow">
      {when && <time dateTime={when}>{when}</time>}
      {topic && (
        <Link className="eyebrow__topic" href={topicPath(topic)}>
          {topic.label}
        </Link>
      )}
      <span>{paper.studyType}</span>
      <span>
        {paper.journal} {paper.year}
      </span>
      <span>來源：{SOURCE_LABELS[paper.source]}</span>
      {isUnreviewed(paper) && <AiChip label="AI 未審" />}
    </p>
  );
}

export function PaperCard({ paper }: { paper: Paper }) {
  return (
    <li className="paper">
      <PaperMeta paper={paper} />
      <h3 className="paper__title">
        <Link href={paperPath(paper)}>{paperLead(paper).title}</Link>
      </h3>
      <p className="paper__result">{paperLead(paper).result}</p>
      <p className="paper__bottom">{paper.bottomLine}</p>
    </li>
  );
}

/** A headline as phrases: lines break between phrases, not inside a word. */
export function Phrases({ item }: { item: Pick<News, "headline"> }) {
  return item.headline.map((part, index) => (
    <span key={index}>
      {part}
      {index < item.headline.length - 1 && <wbr />}
    </span>
  ));
}

export function KeyStat({
  item,
  className,
}: {
  item: News;
  className: string;
}) {
  return (
    <p className={className}>
      <span className="num">
        {item.key.value}
        <span className="stat__unit">{item.key.unit}</span>
      </span>
      <span>{item.key.label}</span>
    </p>
  );
}

export function NewsCard({ item, topic }: { item: News; topic?: Topic }) {
  return (
    <li className="news-card">
      <p className="eyebrow">
        {topic && <span className="eyebrow__topic">{topic.label}</span>}
        <time dateTime={item.publishedAt}>{item.publishedAt}</time>
        {isUnreviewed(item) && <AiChip label="AI 未審" />}
      </p>
      <h3 className="news-card__title">
        <Link href={newsPath(item)} aria-label={headline(item)}>
          <Phrases item={item} />
        </Link>
      </h3>
      <p className="news-card__dek">{item.dek}</p>
      <KeyStat item={item} className="news-card__stat" />
    </li>
  );
}

/** One row of the reading log: a paper or a journal commentary on it (macro `entry`). */
export function Entry({
  update,
  topic,
  level = 3,
}: {
  update: Update;
  topic?: Topic;
  level?: 2 | 3;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  const { paper } = update;
  return (
    <li className="entry">
      {update.kind === "paper" ? (
        <PaperMeta paper={paper} topic={topic} when={update.date} />
      ) : (
        <p className="eyebrow">
          <time dateTime={update.date}>{update.date}</time>
          {topic && (
            <Link className="eyebrow__topic" href={topicPath(topic)}>
              {topic.label}
            </Link>
          )}
          <span>評論</span>
        </p>
      )}
      <Heading className="entry__title">
        <Link href={paperPath(paper)}>
          {update.kind === "paper" ? paperLead(paper).title : update.title}
        </Link>
      </Heading>
      {update.kind === "paper" ? (
        <>
          <p className="entry__result">{paperLead(paper).result}</p>
          <p className="entry__line">{paper.bottomLine}</p>
        </>
      ) : (
        <p className="entry__line">{update.summary}</p>
      )}
    </li>
  );
}

/**
 * Subscribe box (templates/_alerts.html.j2). With a push key (C5 #95) it leads with push, as the current site does;
 * without one it offers RSS only.
 */
export function Alerts() {
  return (
    <section className="alerts" aria-labelledby="alerts-title">
      {pushEnabled ? (
        <>
          <h2 id="alerts-title">新消息一出來就通知你</h2>
          <p>
            開啟推播後，新的消息一發布，手機或電腦就會跳出通知。也可以用 RSS
            訂閱。
          </p>
        </>
      ) : (
        <>
          <h2 id="alerts-title">訂閱新消息</h2>
          <p>把訂閱網址加進 RSS 閱讀器，新的消息與文獻會自動出現。</p>
        </>
      )}
      <div className="alerts__actions">
        {pushEnabled && <PushToggle icon={<Icon name="bell" />} />}
        <a className="btn btn--secondary" href={NEWS_FEED}>
          <Icon name="rss" />
          RSS
        </a>
        <Link className="btn btn--quiet" href="/subscribe/">
          依主題訂閱
        </Link>
      </div>
    </section>
  );
}

/** JSON-LD for the page. "<" is escaped so content can never close the script element. */
export function JsonLd({ data }: { data: object }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(data).replace(/</g, "\\u003c"),
      }}
    />
  );
}
