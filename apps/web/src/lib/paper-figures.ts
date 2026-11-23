// Extracts scale-accurate journal figures directly from a paper's verified `result` and `regimen` strings.
// Strictly read-only presentation: every plotted number comes verbatim from the paper record, never interpolated.
import type { Figure, Paper } from "./site";

type PaperInput = Pick<Paper, "regimen" | "result" | "endpoint">;

const STRIP_TRAILING_PARENS = /\s*[（(][^()（）]*[)）]\s*$/;

/** Splits "Arm A vs Arm B (context)" into two concise arm labels when the regimen is a two-arm comparison. */
export function parseArms(regimen: string): readonly [string, string] | null {
  const cleaned = regimen.replace(STRIP_TRAILING_PARENS, "").trim();
  const parts = cleaned.split(/\s+vs\.?\s+/i);
  if (parts.length !== 2) return null;
  const armA = parts[0].trim();
  const armB = parts[1].replace(STRIP_TRAILING_PARENS, "").trim();
  if (!armA || !armB) return null;
  // Skip multi-arm shorthand ("EC doublet vs triplet vs control" already excluded by length !== 2).
  return [armA, armB];
}

const DURATION_LABEL: Record<string, string> = {
  mos: "中位整體存活（mOS）",
  os: "整體存活（OS）",
  mpfs: "中位無惡化存活（mPFS）",
  pfs: "無惡化存活（PFS）",
  pfs2: "二次無惡化存活（PFS2）",
  mdfs: "中位無病存活（mDFS）",
  dfs: "無病存活（DFS）",
  mefs: "中位無事件存活（mEFS）",
  efs: "無事件存活（EFS）",
  tfs: "無治療存活（TFS）",
  dor: "反應持續時間（DoR）",
};

const RATE_LABEL: Record<string, string> = {
  orr: "客觀反應率（ORR）",
  pcr: "病理完全反應（pCR）",
  ccr: "臨床完全反應（cCR）",
  ccr12: "12 個月臨床完全反應（cCR12）",
  mpr: "主要病理反應（MPR）",
  pmr: "主要病理反應（pMR）",
  mpcr: "主要病理完全反應（mpCR）",
  dcr: "疾病控制率（DCR）",
  cr: "完全反應（CR）",
  "r0 resection": "R0 切除率",
  "path response": "病理反應率",
  "cycle 3 initiated": "進入第 3 療程比例",
};

function labelRate(raw: string): string {
  const norm = raw.trim().replace(/\s+/g, " ");
  const key = norm.toLowerCase();
  if (RATE_LABEL[key]) return RATE_LABEL[key];
  if (/^(?:grade\s*≥?\s*3|g3[+–-]\d*)\s*/i.test(norm)) {
    const rest = norm.replace(/^(?:grade\s*≥?\s*3|g3[+–-]\d*)\s*/i, "").trim();
    return rest ? `Grade ≥3 ${rest}` : "Grade ≥3 不良事件";
  }
  return norm;
}

function labelDuration(raw: string): string {
  const key = raw.trim().toLowerCase();
  return DURATION_LABEL[key] ?? raw.trim();
}

function labelRatio(
  metric: string | undefined,
  kind: string,
  fallbackEndpoint: string,
): string {
  const upperKind = kind.toUpperCase();
  const base =
    metric?.toUpperCase() ||
    (/\b(OS|PFS|DFS|EFS|ORR)\b/i.exec(fallbackEndpoint)?.[1]?.toUpperCase() ??
      "");
  if (upperKind === "HR") return base ? `${base} 風險比（HR）` : "風險比（HR）";
  return base ? `${base} 勝算比（OR）` : "勝算比（OR）";
}

// Duration comparisons: e.g. "mOS 30.3 vs 15.1 mo", "mPFS 12.8 vs 7.1 個月", "PFS2: 20.7 vs 12.9 mo"
const DURATION_COMPARE =
  /\b(mOS|OS|mPFS|PFS2|PFS|mDFS|DFS|mEFS|EFS|TFS|DoR)\s*:?\s*(\d+(?:\.\d+)?)\s+vs\.?\s+(\d+(?:\.\d+)?)\s*(?:mo|months?|個月)/gi;

// Rate comparisons: e.g. "ORR 60.9% vs 40.0%", "G3+ TRAEs 60% vs 37%", "Grade ≥3 TRAE 64.9% vs 44.8%", "R0 resection 18.3% vs 11.6%"
const RATE_COMPARE =
  /\b(ORR|pCR|cCR12|cCR|mPR|pMR|mpCR|DCR|CR|R0 resection|Cycle 3 initiated|(?:Grade\s*≥?\s*3|G3(?:\+|–4|-4))\s+(?:TRAEs?|TEAEs?|AEs?|hand-foot skin reaction))\s*:?\s*(\d+(?:\.\d+)?)%\s+vs\.?\s+(\d+(?:\.\d+)?)%/gi;

// Confidence intervals on log scale: e.g. "HR 0.80, 95% CI 0.69–0.93", "mPFS ... (HR 0.48, 95% CI 0.22-1.04)", "OS HR 0.61 (95% CI 0.46-0.82)"
const INTERVAL_PATTERN =
  /(?:(mOS|OS|mPFS|PFS|DFS|EFS)\s+)?(HR|OR)\s+(\d+(?:\.\d+)?)\s*[（(,]?\s*,?\s*95%\s*CI\s*(\d+(?:\.\d+)?)\s*(?:[-–—~]|to)\s*(\d+(?:\.\d+)?)/gi;

// Single-arm rate meters (only when no two-arm comparison exists): e.g. "ORR 69%", "pCR 68%", "3-yr DFS 100%", "24-mo OS 79%"
const SINGLE_METER =
  /\b((?:\d+-(?:yr|mo)\s+(?:OS|PFS|DFS|EFS))|ORR|pCR|cCR12|cCR|DCR|CR|path response)\s*:?\s*(\d+(?:\.\d+)?)%/gi;

/**
 * Builds up to three compact visual blocks (comparisons, hazard-ratio intervals, or single-arm meters)
 * strictly from the numbers present in `paper.result`. Returns `[]` when the entry has no plottable figures.
 */
export function extractPaperFigures(paper: PaperInput): Figure[] {
  const result = paper.result;
  if (!result) return [];

  const arms = parseArms(paper.regimen);
  const [armA, armB] = arms ?? ["試驗組", "對照組"];

  const durationRows: { label: string; unit: string; a: number; b: number }[] =
    [];
  const seenDuration = new Set<string>();
  for (const match of result.matchAll(DURATION_COMPARE)) {
    const label = labelDuration(match[1]);
    const a = Number(match[2]);
    const b = Number(match[3]);
    if (seenDuration.has(label) || !(a > 0 || b > 0)) continue;
    seenDuration.add(label);
    durationRows.push({ label, unit: "個月", a, b });
  }

  const rateRows: { label: string; unit: string; a: number; b: number }[] = [];
  const seenRate = new Set<string>();
  for (const match of result.matchAll(RATE_COMPARE)) {
    const label = labelRate(match[1]);
    const a = Number(match[2]);
    const b = Number(match[3]);
    if (seenRate.has(label) || a < 0 || a > 100 || b < 0 || b > 100) continue;
    seenRate.add(label);
    rateRows.push({ label, unit: "%", a, b });
  }

  const intervals: Extract<Figure, { kind: "interval" }>[] = [];
  const seenInterval = new Set<string>();
  for (const match of result.matchAll(INTERVAL_PATTERN)) {
    const point = Number(match[3]);
    const low = Number(match[4]);
    const high = Number(match[5]);
    // Respect intervalScale log domain [0.1, 8] and strict ordering low < point < high.
    if (!(low >= 0.1 && high <= 8 && low < point && point < high)) continue;
    const explicitMetric = match[1]?.replace(/^m(?=[A-Z])/, "");
    // Look immediately behind the match (within 40 chars) for an OS/PFS/DFS/EFS cue if not directly adjacent.
    const prefix = result.slice(
      Math.max(0, (match.index ?? 0) - 40),
      match.index ?? 0,
    );
    const nearbyMetric =
      explicitMetric ??
      [...prefix.matchAll(/\b(?:m?(OS|PFS|DFS|EFS))\b/gi)]
        .at(-1)?.[1]
        ?.toUpperCase();
    const label = labelRatio(nearbyMetric, match[2], paper.endpoint);
    const key = `${label}:${point}:${low}:${high}`;
    if (seenInterval.has(key)) continue;
    seenInterval.add(key);
    intervals.push({
      kind: "interval",
      label,
      point,
      low,
      high,
      note:
        match[2].toUpperCase() === "HR"
          ? "< 1 代表試驗組風險較低；虛線 1 為無差異線"
          : undefined,
    });
  }

  const figures: Figure[] = [];

  if (durationRows.length > 0 || rateRows.length > 0) {
    // Only draw two-arm bars when the regimen actually compares two arms, or explicit "vs" comparisons exist.
    const rows = [...durationRows.slice(0, 3), ...rateRows.slice(0, 3)];
    figures.push({ kind: "compare", armA, armB, rows });
  }

  for (const interval of intervals.slice(0, 2)) {
    figures.push(interval);
  }

  // Single-arm meters only when no two-arm comparison was found, avoiding mixing arm-vs-arm and single-arm semantics.
  if (figures.length === 0 && !/\bvs\.?\b/i.test(result)) {
    const meters: { label: string; percent: number }[] = [];
    const seenMeter = new Set<string>();
    for (const match of result.matchAll(SINGLE_METER)) {
      const start = match.index ?? 0;
      // Ignore parenthetical sub-breakdown values (e.g. "影像 cCR 僅 44%（PR 35%, SD 21%）").
      const head = result.slice(0, start);
      const open = (head.match(/[（(]/g) ?? []).length;
      const shut = (head.match(/[）)]/g) ?? []).length;
      if (open > shut) continue;
      const label = labelRate(match[1]);
      const percent = Number(match[2]);
      if (seenMeter.has(label) || percent < 0 || percent > 100) continue;
      seenMeter.add(label);
      meters.push({ label, percent });
    }
    if (meters.length >= 2) {
      figures.push({ kind: "meters", rows: meters.slice(0, 4) });
    }
  }

  return figures;
}
