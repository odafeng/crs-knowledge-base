// Derives a data-driven treatment pathway schematic directly from a topic's verified standardOfCare cards
// and regulatory rows. Never invents regimens or approval statuses outside the API payload.
import type { RegulatoryRow, Topic } from "./site";

export type StageKind =
  "neoadjuvant" | "first-line" | "second-line" | "later" | "general";

export type PathwayStage = {
  id: string;
  cardIndex: number;
  kind: StageKind;
  badge: string;
  title: string;
  regimens: RegulatoryRow[];
};

export type TreatmentPathwayModel = {
  topicLabel: string;
  /** "sequential" connects lines in progression order (1L -> 2L+); "branched" forks distinct clinical settings (e.g. non-metastatic vs metastatic). */
  flow: "single" | "sequential" | "branched";
  stages: PathwayStage[];
};

const STAGE_ORDER: Record<StageKind, number> = {
  neoadjuvant: 0,
  "first-line": 1,
  "second-line": 2,
  later: 3,
  general: 4,
};

function classifyStage(title: string): { kind: StageKind; badge: string } {
  if (/新輔助|術前|非轉移/.test(title)) {
    return { kind: "neoadjuvant", badge: "非轉移性・新輔助" };
  }
  if (/第一線|一線|\b1L\b/i.test(title)) {
    return { kind: "first-line", badge: "轉移性・第一線（1L）" };
  }
  if (/第二線|\b2L\+?\b/i.test(title)) {
    return { kind: "second-line", badge: "二線以上（2L+）" };
  }
  if (/後線|三線|\b3L\+?\b/i.test(title)) {
    return { kind: "later", badge: "後線治療" };
  }
  return { kind: "general", badge: "治療選項" };
}

/**
 * Builds the pathway schematic from standardOfCare cards that carry checked regulatory rows.
 * Returns null when a topic has no structured regulatory regimens (e.g. generic-CRS).
 */
export function buildTreatmentPathway(
  topic: Pick<Topic, "label" | "standardOfCare">,
): TreatmentPathwayModel | null {
  const stages: PathwayStage[] = [];
  topic.standardOfCare.forEach((card, cardIndex) => {
    const regimens = card.regulatory ?? [];
    if (regimens.length === 0) return;
    const { kind, badge } = classifyStage(card.title);
    stages.push({
      id: `soc-${cardIndex}`,
      cardIndex,
      kind,
      badge,
      title: card.title,
      regimens,
    });
  });

  if (stages.length === 0) return null;

  stages.sort(
    (a, b) =>
      STAGE_ORDER[a.kind] - STAGE_ORDER[b.kind] || a.cardIndex - b.cardIndex,
  );

  const hasNeoadjuvant = stages.some((s) => s.kind === "neoadjuvant");
  const hasMetastatic = stages.some(
    (s) =>
      s.kind === "first-line" || s.kind === "second-line" || s.kind === "later",
  );

  const flow: TreatmentPathwayModel["flow"] =
    stages.length === 1
      ? "single"
      : hasNeoadjuvant && hasMetastatic
        ? "branched"
        : "sequential";

  return {
    topicLabel: topic.label,
    flow,
    stages,
  };
}
