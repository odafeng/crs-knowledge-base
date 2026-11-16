// Building blocks of the reading pages, ported from templates/_macros.html.j2.
import Link from "next/link";
import {
  headline,
  isUnreviewed,
  newsPath,
  paperPath,
  SOURCE_LABELS,
  STATUS_LABELS,
  STATUS_STYLE,
  topicPath,
  type Crumbs,
  type News,
  type Paper,
  type Topic,
} from "@/lib/site";

// Inline SVG paths from sitegen/icons.py (24x24, stroke); constant strings, never user content.
const ICONS = {
  news: '<path d="M5 5h11v14H7a2 2 0 0 1-2-2z"/><path d="M16 9h3v8a2 2 0 0 1-2 2"/><path d="M8 9h5M8 12.5h5M8 16h3"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 2"/>',
  x: '<path d="m7 7 10 10M17 7 7 17"/>',
  question:
    '<path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7"/><path d="M12 17h.01"/>',
  spark:
    '<path d="m12 4 1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z"/><path d="M18.5 15.5v3M17 17h3"/>',
  external:
    '<path d="M14 5h5v5M19 5l-8 8"/><path d="M11 6H6a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-5"/>',
} as const;

export function Icon({ name }: { name: keyof typeof ICONS }) {
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
  return (
    <span className="chip chip--ai">
      <Icon name="spark" />
      {label}
    </span>
  );
}

export function Status({
  regulator,
  value,
}: {
  regulator: keyof typeof STATUS_LABELS;
  value: string;
}) {
  const [style, glyph] = STATUS_STYLE[value] ?? STATUS_STYLE.unknown;
  const labels: Record<string, string> = STATUS_LABELS[regulator];
  return (
    <span className={`status status--${style}`}>
      <Icon name={glyph as keyof typeof ICONS} />
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
        <Link href={paperPath(paper)}>{paper.regimen}</Link>
      </h3>
      <p className="paper__result">{paper.result}</p>
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
