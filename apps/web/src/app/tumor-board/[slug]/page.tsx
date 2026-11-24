import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { PrintButton } from "@/components/print-button";
import { RichHtml, Status } from "@/components/reading";
import { getTopicBySlug, listPapers } from "@/lib/content";
import { pageMetadata } from "@/lib/seo";
import { byTopic, doiUrl, topicPath } from "@/lib/site";
import { boardPath, boardTopics, tumorBoard } from "@/lib/tumor-board";

export const revalidate = 3600;
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const topic = await getTopicBySlug((await params).slug);
  if (!topic) return {};
  // The same content as the topic page, rearranged for printing: keep it out of search results.
  return pageMetadata(
    `${topic.label} tumor board 摘要`,
    `${topic.title}的治療現況、核准與給付狀態及關鍵試驗，一頁可列印。`,
    boardPath(topic),
    { indexable: false },
  );
}

const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

export default async function TumorBoardPage({ params }: Props) {
  const topic = await getTopicBySlug((await params).slug);
  if (!topic || boardTopics([topic]).length === 0) notFound();
  const board = tumorBoard(topic, byTopic(await listPapers(), topic.key));

  return (
    <div className="container page board">
      <header className="page-head board__head">
        <p className="eyebrow">GutHub・Tumor board 摘要</p>
        <h1>{topic.title}</h1>
        <p className="board__meta">
          資料日期 {board.asOf}
          ・內容取自本站的治療卡片與文獻整理，未新增任何數字。
          臨床決策請以原始文獻、現行指引與病人個別狀況為準。
        </p>
        <div className="actions board__actions">
          <PrintButton />
          <Link className="btn btn--secondary" href={topicPath(topic)}>
            回到主題頁
          </Link>
        </div>
      </header>

      <section aria-labelledby="board-soc">
        <h2 id="board-soc">治療現況</h2>
        {board.cards.map((card) => (
          <div className="board__card" key={card.title}>
            <h3>{card.title}</h3>
            <RichHtml html={card.html} label={card.title} role="group" />
            <p className="note">最近複查 {card.reviewedAt}</p>
          </div>
        ))}
      </section>

      {board.regulatory.length > 0 && (
        <section aria-labelledby="board-reg">
          <h2 id="board-reg">核准與給付（台灣與 FDA）</h2>
          <div
            className="table-wrap"
            tabIndex={0}
            role="region"
            aria-label="核准與給付表格，可左右捲動"
          >
            <table className="table board__table">
              <thead>
                <tr>
                  <th scope="col">方案</th>
                  <th scope="col">FDA</th>
                  <th scope="col">TFDA</th>
                  <th scope="col">健保</th>
                  <th scope="col">查核日與出處</th>
                </tr>
              </thead>
              <tbody>
                {board.regulatory.map((row) => (
                  <tr key={row.regimen}>
                    <td>
                      {row.regimen}
                      {[row.fdaNote, row.tfdaNote, row.nhiNote]
                        .filter(Boolean)
                        .map((note) => (
                          <span className="note" key={note}>
                            {note}
                          </span>
                        ))}
                    </td>
                    <td>
                      <Status regulator="fda" value={row.fda} />
                    </td>
                    <td>
                      <Status regulator="tfda" value={row.tfda} />
                    </td>
                    <td>
                      <Status regulator="nhi" value={row.nhi} />
                    </td>
                    <td>
                      {row.checkedAt}
                      {(row.sources ?? []).map((url) => (
                        <a className="note" href={url} rel="noopener" key={url}>
                          {host(url)}
                        </a>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {board.trials.length > 0 && (
        <section aria-labelledby="board-trials">
          <h2 id="board-trials">卡片引用的試驗</h2>
          <ol className="board__trials">
            {board.trials.map((trial) => (
              <li key={trial.id}>
                <Link href={trial.path}>{trial.label}</Link>
                <span>
                  {trial.studyType}
                  {trial.n != null && trial.n !== "" ? `，n=${trial.n}` : ""}：
                  {trial.result}
                </span>
                {trial.doi && (
                  <a className="note" href={doiUrl(trial.doi)} rel="noopener">
                    doi:{trial.doi}
                  </a>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
