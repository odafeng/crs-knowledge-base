import { describe, expect, it } from "vitest";
import { applyFontSize, nextTheme, PREFS_SCRIPT } from "./prefs";

describe("nextTheme", () => {
  it("flips the system setting when the reader has not chosen", () => {
    expect(nextTheme(undefined, false)).toBe("dark");
    expect(nextTheme(undefined, true)).toBe("light");
  });

  it("flips an explicit choice regardless of the system", () => {
    expect(nextTheme("dark", false)).toBe("light");
    expect(nextTheme("light", true)).toBe("dark");
  });
});

describe("text size", () => {
  const root = () => ({ dataset: {} }) as unknown as HTMLElement;

  it("stores only non-default sizes on <html>", () => {
    const html = root();
    applyFontSize(html, "xl");
    expect(html.dataset.fontSize).toBe("xl");
    applyFontSize(html, "md");
    expect(html.dataset.fontSize).toBeUndefined();
  });

  it("applies saved preferences before paint and survives blocked storage", () => {
    const run = (storage: Record<string, string> | null) => {
      const documentElement = root();
      const localStorage = {
        getItem: (key: string) => {
          if (!storage) throw new Error("SecurityError");
          return storage[key] ?? null;
        },
      };
      new Function("document", "localStorage", PREFS_SCRIPT)(
        { documentElement },
        localStorage,
      );
      return documentElement.dataset;
    };
    expect(run({ theme: "dark", fontSize: "lg" })).toEqual({
      theme: "dark",
      fontSize: "lg",
    });
    expect(run({ fontSize: "md" })).toEqual({});
    expect(run(null)).toEqual({});
  });
});
