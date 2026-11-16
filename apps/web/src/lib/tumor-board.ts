// A one-page tumor board sheet per molecular topic (G7 #118). It only rearranges what the topic page already shows:
// treatment cards, approval and coverage rows with their sources, and the trials the cards cite. No number is added
// or rewritten, so every figure on the sheet can be traced to a reviewed entry.
import {
  paperPath,
  paperTitle,
  repairCardHtml,
  type Paper,
  type Topic,
} from "./site";

export type Board = ReturnType<typeof tumorBoard>;

/** Topics with treatment cards; the robotic topic has its own section pages and no cards. */
export function boardTopics(topics: Topic[]): Topic[] {
  return topics.filter(
    (t) => t.standardOfCare.length > 0 && t.roboticSections.length === 0,
  );
}

export const boardPath = (topic: Pick<Topic, "slug">) =>
  `/tumor-board/${topic.slug}/`;

export function tumorBoard(topic: Topic, papers: Paper[]) {
  const byId = new Map(papers.map((p) => [p.id, p]));
  const cited = [...new Set(topic.standardOfCare.flatMap((card) => card.refs))];
  const regulatory = topic.standardOfCare.flatMap(
    (card) => card.regulatory ?? [],
  );
  const dates = [
    ...topic.standardOfCare.map((card) => card.reviewedAt),
    ...regulatory.map((row) => row.checkedAt),
  ];
  return {
    cards: topic.standardOfCare.map((card) => ({
      title: card.title,
      html: repairCardHtml(card.body_html),
      reviewedAt: card.reviewedAt,
    })),
    regulatory,
    trials: cited.flatMap((id) => {
      const paper = byId.get(id);
      if (!paper) return [];
      return [
        {
          id,
          label: paperTitle(paper),
          studyType: paper.studyType,
          n: paper.n,
          result: paper.result,
          doi: paper.doi ?? null,
          path: paperPath(paper),
        },
      ];
    }),
    asOf: dates.sort().at(-1) ?? null,
  };
}
