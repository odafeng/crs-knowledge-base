import { describe, expect, it } from "vitest";
import { barWidth, fmt, intervalScale } from "./figures";

// Expected values were computed with sitegen/figures.py on the real figures in data/news.json.
describe("figure geometry (ported from sitegen/figures.py)", () => {
  it("prints numbers as the source wrote them", () => {
    // Python's "{:g}" switches to exponents beyond these magnitudes; no story uses such values.
    expect([30, 30.3, 0.48, 7.7, 4.0, 100, 0.25].map(fmt)).toEqual([
      "30",
      "30.3",
      "0.48",
      "7.7",
      "4",
      "100",
      "0.25",
    ]);
  });

  it("draws percentages against 100 and other units on a shared scale", () => {
    const rows = [
      { label: "ORR", unit: "%", a: 38.9, b: 16.7 },
      { label: "mPFS", unit: "個月", a: 7.7, b: 4.0 },
    ];
    expect(
      rows.map((row) => [
        barWidth(rows, row, row.a),
        barWidth(rows, row, row.b),
      ]),
    ).toEqual([
      [38.9, 16.7],
      [100, 51.9],
    ]);
  });

  it("places a hazard ratio and its interval on a log scale with the same ticks", () => {
    const { x, ticks } = intervalScale({ low: 0.22, high: 1.04 });
    expect([x(0.22), x(0.48), x(1.04), x(1)]).toEqual([26.3, 52.4, 78.2, 76.9]);
    expect(ticks).toEqual([
      ["0.1", 0],
      ["0.25", 30.6],
      ["0.5", 53.7],
      ["1", 76.9],
      ["2", 100],
    ]);
  });
});
