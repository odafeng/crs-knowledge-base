// Splits text into plain runs and the figures a reader scans for (I3 #192): numbers with their unit, so
// "從 15.1 延長到 30.3 個月" can mark "15.1" and "30.3 個月". Purely presentational; the text is unchanged.
const FIGURE =
  /((?:HR|OR|ORR|P|p)\s?[<=≤]\s?\d+(?:\.\d+)?|\d+(?:\.\d+)?(?:\s?(?:%|個月|mo|months?|年|位|例|人|mg\/kg|mg))?)/g;

// Clinical classifiers whose following numeral (or range like "ECOG 0-2", "Phase 1/2") is a label, not an outcome.
const LABEL_PREFIX =
  /\b(?:exon|codon|intron|phase|stage|grade|ecog|ps|cohort|arm|group|line|recist|ctcae|ajcc|tnm|figo|version)\s*(?:\d+(?:\.\d+)?\s*[-–/]\s*)?$/i;

// Age expression ("18-75 歲", "65 歲") following a bare number.
const AGE_SUFFIX = /^(?:\s*[-–~～]\s*\d+)?\s*歲/;

export type Run = { text: string; figure: boolean };

export function figures(text: string): Run[] {
  const runs: Run[] = [];
  let last = 0;
  for (const match of text.matchAll(FIGURE)) {
    const start = match.index ?? 0;
    const token = match[0];
    const end = start + token.length;
    // Figures in brackets are the detail (a confidence interval, a P value); the eye should land on the result.
    const head = text.slice(0, start);
    const tail = text.slice(end);
    const open = (head.match(/[（(]/g) ?? []).length;
    const shut = (head.match(/[）)]/g) ?? []).length;
    if (open > shut) continue;
    const hasStatPrefix = /^(?:HR|OR|ORR|P|p)\s?[<=≤]/.test(token);
    const hasUnit = /(%|個月|mo|months?|年|位|例|人|mg\/kg|mg)$/.test(token);
    // A digit inside a name (V600E, mFOLFOX6, PD-1, 5-FU, TAS-102) is not a result.
    const before = text[start - 1] ?? "";
    const after = text[end] ?? "";
    if (!hasStatPrefix && /[A-Za-z]/.test(before)) continue;
    if (!hasStatPrefix && !hasUnit) {
      // Hyphenated drug/target names (PD-1, CTLA-4, 5-FU, TAS-102) and ratios (1:1, 2:1).
      if (
        (before === "-" && /[A-Za-z]-$/.test(head)) ||
        (after === "-" && /^-[A-Za-z]/.test(tail)) ||
        before === ":" ||
        after === ":"
      ) {
        continue;
      }
      // Clinical classifiers (KRAS exon 2, ECOG 0-2, Grade 3, Phase 3) and age ranges (18-75 歲).
      if (LABEL_PREFIX.test(head) || AGE_SUFFIX.test(tail)) continue;
    }
    if (start > last)
      runs.push({ text: text.slice(last, start), figure: false });
    runs.push({ text: token, figure: true });
    last = end;
  }
  if (last < text.length) runs.push({ text: text.slice(last), figure: false });
  return runs;
}
