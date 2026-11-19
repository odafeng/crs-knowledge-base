// A drug's evidence as a history (J2): every study that names the drug, oldest first, each opened to its summary
// (ADR-0025) so the page reads as the drug's record without clicking into each paper. A paper without a summary
// falls back to its entry's result and bottom line.
import Link from "next/link";
import { Marked } from "@/components/paper-summary";
import { AiChip } from "@/components/reading";
import { needsReview } from "@/lib/review";
import type { Paper, Topic } from "@/lib/site";
import { paperLead, paperPath, topicPath } from "@/lib/site";

export function DrugEvidence({
  papers,
  topicOf,
}: {
  papers: readonly Paper[];
  topicOf: (key: string) => Topic | undefined;
}) {
  return (
    <ol className="evidence">
      {papers.map((paper) => {
        const { summary } = paper;
        const topic = topicOf(paper.topic);
        return (
          <li className="evidence__study" key={paper.id}>
            <p className="evidence__when">
              <span className="evidence__year">{paper.year}</span>
              <span>{paper.journal}</span>
              <span>{paper.studyType}</span>
              {paper.n != null && <span>n = {paper.n}</span>}
              {topic && <Link href={topicPath(topic)}>{topic.label}</Link>}
            </p>
            <div className="evidence__body">
              <h2 className="evidence__title">
                <Link href={paperPath(paper)}>{paperLead(paper).title}</Link>
                {needsReview(paper) && <AiChip label="AI 未審" />}
              </h2>
              <p className="evidence__takeaway">
                <Marked text={paperLead(paper).result} />
              </p>
              {summary ? (
                <dl className="evidence__facts">
                  <div>
                    <dt>收了誰</dt>
                    <dd>
                      <Marked text={summary.population} />
                    </dd>
                  </div>
                  <div>
                    <dt>比什麼</dt>
                    <dd>{summary.comparison}</dd>
                  </div>
                  <div className="evidence__results">
                    <dt>主要結果</dt>
                    <dd>
                      <ul>
                        {summary.findings.map((item) => (
                          <li key={item}>
                            <Marked text={item} />
                          </li>
                        ))}
                      </ul>
                    </dd>
                  </div>
                  <div className="evidence__limits">
                    <dt>要小心</dt>
                    <dd>
                      <ul>
                        {summary.limits.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </dd>
                  </div>
                </dl>
              ) : (
                <p className="evidence__line">{paper.bottomLine}</p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
