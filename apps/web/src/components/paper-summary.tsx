// The at-a-glance block at the top of a paper page (I3 #192, ADR-0025), set like a journal's visual abstract:
// the finding in one line on the blue field with its figures highlighted, then who was studied, what was compared
// and what came out, read left to right, then what it means and what to be careful about. Plain text from the
// API, rendered as text. Taiwan approval and reimbursement come from the topic's checked table, never the summary.
import Link from "next/link";
import type { components } from "@/lib/api.generated";
import { figures } from "@/lib/highlight";
import type { Topic } from "@/lib/site";
import { topicPath } from "@/lib/site";
import styles from "./paper-summary.module.css";

type Summary = components["schemas"]["PaperSummary"];

/** Text with its figures marked, the way a reader runs a highlighter over the numbers in a results section. */
export function Marked({ text }: { text: string }) {
  return figures(text).map((run, index) =>
    run.figure ? (
      <mark className="hl" key={index}>
        {run.text}
      </mark>
    ) : (
      run.text
    ),
  );
}

const WARN =
  '<path d="M12 4 2.5 20h19z"/><path d="M12 10v4.5"/><circle cx="12" cy="17.25" r=".6"/>';

function Glyph({ paths }: { paths: string }) {
  return (
    <svg
      className={styles.glyph}
      viewBox="0 0 24 24"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: paths }}
    />
  );
}

export function PaperGlance({
  summary,
  topic,
}: {
  summary: Summary;
  topic: Topic | undefined;
}) {
  const [lead, ...rest] = summary.findings;
  return (
    <section className={styles.glance} aria-labelledby="glance-title">
      <h2 id="glance-title" className="visually-hidden">
        速覽
      </h2>
      <div className={styles.flow}>
        <div className={styles.step}>
          <h3 className={styles.heading}>
            <span className={styles.stepNum} aria-hidden="true">
              01
            </span>
            收了誰
          </h3>
          <p>
            <Marked text={summary.population} />
          </p>
        </div>
        <div className={styles.step}>
          <h3 className={styles.heading}>
            <span className={styles.stepNum} aria-hidden="true">
              02
            </span>
            比什麼
          </h3>
          <p>{summary.comparison}</p>
        </div>
        <div className={`${styles.step} ${styles.stepResult}`}>
          <h3 className={styles.heading}>
            <span className={styles.stepNum} aria-hidden="true">
              03
            </span>
            主要結果
          </h3>
          <p className={styles.leadFinding}>
            <Marked text={lead} />
          </p>
          {rest.length > 0 && (
            <ul>
              {rest.map((item) => (
                <li key={item}>
                  <Marked text={item} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className={styles.meaning}>
        <h3 className={styles.heading}>代表什麼</h3>
        <p>{summary.meaning}</p>
      </div>
      <div className={styles.caution}>
        <h3 className={styles.heading}>
          <Glyph paths={WARN} />
          要小心
        </h3>
        <ul>
          {summary.limits.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
      {topic && (
        <p className={styles.taiwan}>
          台灣的 TFDA 核准與健保給付，看
          <Link href={`${topicPath(topic)}#reg`}>
            {topic.label} 的核准與給付現況
          </Link>
          。
        </p>
      )}
    </section>
  );
}

/** The finding in one line, set on the ink-navy field like a clinical journal visual abstract. */
export function GlanceFinding({ summary }: { summary: Summary }) {
  return (
    <div className={styles.finding} role="note" aria-label="一句話結論">
      <p className={styles.findingKicker}>臨床問題與結論</p>
      <p className={styles.findingQuestion}>{summary.question}</p>
      <p className={styles.findingLine}>
        <Marked text={summary.takeaway} />
      </p>
    </div>
  );
}
