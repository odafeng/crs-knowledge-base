import { describe, expect, it } from "vitest";
import { dailyLabel } from "./daily";

describe("the home page's daily item says how fresh it is", () => {
  it("calls today's pick today's", () => {
    expect(dailyLabel("2026-11-17", "2026-11-17")).toBe("今天的一件事");
  });

  it("dates a pick from an earlier day", () => {
    expect(dailyLabel("2026-11-13", "2026-11-17")).toBe(
      "最近的一件事・11 月 13 日",
    );
  });
});
