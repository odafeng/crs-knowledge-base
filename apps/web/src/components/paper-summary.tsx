// The at-a-glance block at the top of a paper page (I3 #192, ADR-0025): what the study asked, in whom, against
// what, what it found, what it means and what to be careful about, in Traditional Chinese. Plain text from the API,
// rendered as text. Taiwan approval and reimbursement come from the topic's checked table, never from the summary.
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import type { Topic } from "@/lib/site";
import { topicPath } from "@/lib/site";

type Summary = components["schemas"]["PaperSummary"];

export function PaperGlance({
  summary,
  topic,
}: {
  summary: Summary;
  topic: Topic | undefined;
}) {
  return (
    <section className="glance" aria-labelledby="glance-title">
      <h2 id="glance-title" className="visually-hidden">
        速覽
      </h2>
      <p className="glance__question">
        <span className="glance__label">這篇在問</span>
        {summary.question}
      </p>
      <dl className="glance__grid">
        <div className="glance__cell">
          <dt className="glance__label">收了誰</dt>
          <dd>{summary.population}</dd>
        </div>
        <div className="glance__cell">
          <dt className="glance__label">比什麼</dt>
          <dd>{summary.comparison}</dd>
        </div>
      </dl>
      <div className="glance__block glance__block--findings">
        <h3 className="glance__label">主要結果</h3>
        <ul>
          {summary.findings.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
      <div className="glance__block">
        <h3 className="glance__label">代表什麼</h3>
        <p>{summary.meaning}</p>
      </div>
      <div className="glance__block glance__block--limits">
        <h3 className="glance__label">要小心</h3>
        <ul>
          {summary.limits.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
      {topic && (
        <p className="glance__taiwan">
          <span className="glance__label">台灣</span>
          TFDA 核准與健保給付請看
          <Link href={`${topicPath(topic)}#reg`}>
            {topic.label} 的核准與給付現況
          </Link>
          。
        </p>
      )}
    </section>
  );
}
