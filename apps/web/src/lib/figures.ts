// Geometry for news figures, ported from sitegen/figures.py. Every value is drawn from the story's structured data.

/** 30 -> "30", 30.3 -> "30.3": print a number the way the source wrote it (Python's "{:g}" for these magnitudes). */
export function fmt(value: number): string {
  return String(Number(value.toPrecision(6)));
}

const round1 = (value: number) => Math.round(value * 10) / 10;

type CompareRow = { label: string; unit: string; a: number; b: number };

/**
 * Bar length in percent of the track, zero-based. Rows in the same unit share one scale, so 12.8 months is drawn
 * shorter than 30.3 months; a percentage is drawn against 100.
 */
export function barWidth(
  rows: readonly CompareRow[],
  row: CompareRow,
  value: number,
): number {
  if (row.unit === "%") return round1(value);
  const top = Math.max(
    ...rows.filter((r) => r.unit === row.unit).flatMap((r) => [r.a, r.b]),
  );
  return round1((100 * value) / top);
}

const TICKS = [0.1, 0.25, 0.5, 1, 2, 4, 8];

/** A ratio with its confidence interval on a log scale around `reference` (1 for HR/OR). */
export function intervalScale(
  interval: { low: number; high: number },
  reference = 1,
) {
  const low = Math.max(
    ...TICKS.filter((t) => t <= Math.min(interval.low, reference)),
  );
  const high = Math.min(
    ...TICKS.filter((t) => t >= Math.max(interval.high, reference)),
  );
  const x = (value: number) =>
    round1(
      (100 * (Math.log(value) - Math.log(low))) /
        (Math.log(high) - Math.log(low)),
    );
  const ticks = TICKS.filter((t) => low <= t && t <= high).map(
    (t) => [fmt(t), x(t)] as const,
  );
  return { x, ticks };
}
