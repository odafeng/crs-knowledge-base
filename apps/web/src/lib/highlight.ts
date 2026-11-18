// Splits text into plain runs and the figures a reader scans for (I3 #192): numbers with their unit, so
// "從 15.1 延長到 30.3 個月" can mark "15.1" and "30.3 個月". Purely presentational; the text is unchanged.
const FIGURE =
  /((?:HR|OR|ORR|P|p)\s?[<=≤]\s?\d+(?:\.\d+)?|\d+(?:\.\d+)?(?:\s?(?:%|個月|mo|months?|年|位|例|人|mg\/kg|mg))?)/g;

export type Run = { text: string; figure: boolean };

export function figures(text: string): Run[] {
  const runs: Run[] = [];
  let last = 0;
  for (const match of text.matchAll(FIGURE)) {
    const start = match.index ?? 0;
    // Figures in brackets are the detail (a confidence interval, a P value); the eye should land on the result.
    const head = text.slice(0, start);
    const open = (head.match(/[（(]/g) ?? []).length;
    const shut = (head.match(/[）)]/g) ?? []).length;
    if (open > shut) continue;
    // A digit inside a name (V600E, mFOLFOX6, stage 2) is not a result.
    const before = text[start - 1] ?? "";
    if (/[A-Za-z]/.test(before) && !/^(HR|OR|ORR|P|p)/.test(match[0])) continue;
    if (start > last)
      runs.push({ text: text.slice(last, start), figure: false });
    runs.push({ text: match[0], figure: true });
    last = start + match[0].length;
  }
  if (last < text.length) runs.push({ text: text.slice(last), figure: false });
  return runs;
}
