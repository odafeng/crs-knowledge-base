import { describe, expect, it } from "vitest";
import {
  DRUG_GROUPS,
  DRUGS,
  drugByBrand,
  drugBySlug,
  drugCounts,
  drugPath,
  drugShelves,
  drugsOf,
  evidenceOrder,
  papersOf,
} from "./drugs";
import type { Paper } from "./site";

const slugs = (regimen: string, summary?: Partial<Paper["summary"]>) =>
  drugsOf({ regimen, summary: summary as Paper["summary"] }).map((d) => d.slug);

describe("drugs", () => {
  it("reads a drug from its name, short forms and the regimen as written", () => {
    expect(slugs("Regorafenib 160 mg vs placebo")).toEqual(["regorafenib"]);
    // A network meta-analysis writes doses into the short form.
    expect(
      slugs("FTD-TPI±bev/RAM vs fruquintinib vs Rego160 vs Rego80+"),
    ).toEqual([
      "bevacizumab",
      "ramucirumab",
      "regorafenib",
      "fruquintinib",
      "trifluridine-tipiracil",
    ]);
    expect(slugs("Neoadjuvant nivo + ipi (colon)")).toEqual([
      "nivolumab",
      "ipilimumab",
    ]);
  });

  it("counts the control arm too", () => {
    expect(
      slugs("Sotorasib 960mg + panitumumab vs TAS-102/regorafenib"),
    ).toEqual([
      "regorafenib",
      "panitumumab",
      "sotorasib",
      "trifluridine-tipiracil",
    ]);
  });

  it("reads EC as encorafenib plus cetuximab", () => {
    expect(slugs("EC+mFOLFOX6 vs SOC (1L)")).toEqual([
      "cetuximab",
      "encorafenib",
    ]);
  });

  it("keeps trastuzumab deruxtecan apart from trastuzumab", () => {
    expect(slugs("Trastuzumab deruxtecan (T-DXd)")).toEqual([
      "trastuzumab-deruxtecan",
    ]);
    expect(slugs("Pertuzumab + trastuzumab")).toEqual([
      "trastuzumab",
      "pertuzumab",
    ]);
  });

  it("matches whole words only, and capitalised abbreviations only in capitals", () => {
    expect(slugs("A programme of care for SEC patients")).toEqual([]);
    expect(slugs("bot and bal")).toEqual([]);
    expect(slugs("BOT + BAL")).toEqual(["botensilimab", "balstilimab"]);
  });

  it("also reads the summary's title and comparison", () => {
    expect(
      slugs("Neoadjuvant anti-PD-1", {
        title: "x",
        comparison: "術前 pembrolizumab 單藥",
      }),
    ).toEqual(["pembrolizumab"]);
  });

  it("lists drugs most papers first and leaves out drugs no paper names", () => {
    const papers = [
      { regimen: "Regorafenib vs placebo" },
      { regimen: "Regorafenib 80 mg escalation" },
      { regimen: "Fruquintinib vs placebo" },
    ];
    expect(drugCounts(papers).map((r) => [r.drug.slug, r.count])).toEqual([
      ["regorafenib", 2],
      ["fruquintinib", 1],
    ]);
    expect(papersOf(drugBySlug("fruquintinib")!, papers)).toEqual([papers[2]]);
  });

  it("shelves drugs by class, the class most papers name first, each paper once per class", () => {
    const papers = [
      { regimen: "Encorafenib + binimetinib + cetuximab" },
      { regimen: "Encorafenib + cetuximab" },
      { regimen: "Pembrolizumab vs chemotherapy" },
      { regimen: "Nivolumab + ipilimumab" },
      { regimen: "Dostarlimab" },
    ];
    const shelves = drugShelves(papers).map((shelf) => [
      shelf.group,
      shelf.papers,
      shelf.rows.map((r) => [r.drug.slug, r.count]),
    ]);
    expect(shelves).toEqual([
      [
        "immune",
        3,
        [
          ["dostarlimab", 1],
          ["ipilimumab", 1],
          ["nivolumab", 1],
          ["pembrolizumab", 1],
        ],
      ],
      // A tie keeps the order of DRUG_GROUPS
      ["egfr", 2, [["cetuximab", 2]]],
      // Two papers, though encorafenib (2) and binimetinib (1) add up to three
      [
        "braf",
        2,
        [
          ["encorafenib", 2],
          ["binimetinib", 1],
        ],
      ],
    ]);
  });

  it("has unique slugs and a known group for every drug", () => {
    expect(new Set(DRUGS.map((d) => d.slug)).size).toBe(DRUGS.length);
    const groups = new Set(DRUG_GROUPS.map(([g]) => g));
    expect(DRUGS.every((d) => groups.has(d.group))).toBe(true);
    expect(drugPath({ slug: "regorafenib" })).toBe("/drugs/regorafenib/");
  });

  it("finds a drug by its brand, whatever the case", () => {
    expect(drugByBrand("stivarga")?.slug).toBe("regorafenib");
    expect(drugByBrand("LONSURF")?.slug).toBe("trifluridine-tipiracil");
    expect(drugByBrand("regorafenib")).toBeUndefined();
  });

  it("orders a drug's evidence oldest first, same-year papers as the site had them", () => {
    const papers = [
      { id: "stellar", year: 2025 },
      { id: "correct", year: 2013 },
      { id: "liu", year: 2025 },
      { id: "concur", year: 2015 },
    ];
    expect(evidenceOrder(papers).map((p) => p.id)).toEqual([
      "correct",
      "concur",
      "stellar",
      "liu",
    ]);
  });
});
