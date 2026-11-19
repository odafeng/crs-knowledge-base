// Browse papers by drug (J1 #205, ADR-0026). A hand-kept list: a paper belongs to a drug when its regimen, or its
// summary's title or comparison, names the drug, whether as the studied treatment or as the control arm.
import type { Crumbs, Paper } from "./site";
import { HOME } from "./site";

export type DrugGroup =
  | "antiangiogenic"
  | "egfr"
  | "braf"
  | "kras"
  | "her2"
  | "immune"
  | "oral-chemo"
  | "other";

export type Drug = {
  slug: string;
  name: string;
  brand?: string;
  group: DrugGroup;
  /** Patterns read case-insensitively as whole words: generic names and common short forms ("rego", "bev"). */
  names: readonly string[];
  /** Patterns read case-sensitively, for capitalised abbreviations ("EC", "RAM") that are also ordinary letters. */
  abbreviations?: readonly string[];
};

export const DRUG_GROUPS: readonly [DrugGroup, string][] = [
  ["antiangiogenic", "抗血管新生"],
  ["egfr", "抗 EGFR"],
  ["braf", "BRAF／MEK 抑制劑"],
  ["kras", "KRAS G12C 抑制劑"],
  ["her2", "抗 HER2"],
  ["immune", "免疫檢查點抑制劑"],
  ["oral-chemo", "口服化療"],
  ["other", "其他"],
];

// One row per drug, so the list reads as a table.
// prettier-ignore
export const DRUGS: readonly Drug[] = [
  { slug: "bevacizumab", name: "Bevacizumab", brand: "Avastin", group: "antiangiogenic", names: ["bevacizumab", "bev"] },
  { slug: "ramucirumab", name: "Ramucirumab", brand: "Cyramza", group: "antiangiogenic", names: ["ramucirumab"], abbreviations: ["RAM"] },
  { slug: "regorafenib", name: "Regorafenib", brand: "Stivarga", group: "antiangiogenic", names: ["regorafenib", "rego"] },
  { slug: "fruquintinib", name: "Fruquintinib", brand: "Fruzaqla", group: "antiangiogenic", names: ["fruquintinib"] },
  { slug: "zanzalintinib", name: "Zanzalintinib", group: "antiangiogenic", names: ["zanzalintinib"] },
  { slug: "cetuximab", name: "Cetuximab", brand: "Erbitux", group: "egfr", names: ["cetuximab", "cetux"], abbreviations: ["EC"] },
  { slug: "panitumumab", name: "Panitumumab", brand: "Vectibix", group: "egfr", names: ["panitumumab"] },
  { slug: "encorafenib", name: "Encorafenib", brand: "Braftovi", group: "braf", names: ["encorafenib"], abbreviations: ["EC"] },
  { slug: "binimetinib", name: "Binimetinib", brand: "Mektovi", group: "braf", names: ["binimetinib"] },
  { slug: "sotorasib", name: "Sotorasib", brand: "Lumakras", group: "kras", names: ["sotorasib"] },
  { slug: "adagrasib", name: "Adagrasib", brand: "Krazati", group: "kras", names: ["adagrasib"] },
  { slug: "divarasib", name: "Divarasib", group: "kras", names: ["divarasib"] },
  { slug: "garsorasib", name: "Garsorasib", group: "kras", names: ["garsorasib"] },
  { slug: "trastuzumab", name: "Trastuzumab", brand: "Herceptin", group: "her2", names: ["trastuzumab(?! deruxtecan)"] },
  { slug: "pertuzumab", name: "Pertuzumab", brand: "Perjeta", group: "her2", names: ["pertuzumab"] },
  { slug: "tucatinib", name: "Tucatinib", brand: "Tukysa", group: "her2", names: ["tucatinib"] },
  { slug: "trastuzumab-deruxtecan", name: "Trastuzumab deruxtecan", brand: "Enhertu", group: "her2", names: ["trastuzumab deruxtecan"], abbreviations: ["T-DXd"] },
  { slug: "pembrolizumab", name: "Pembrolizumab", brand: "Keytruda", group: "immune", names: ["pembrolizumab", "pembro"] },
  { slug: "nivolumab", name: "Nivolumab", brand: "Opdivo", group: "immune", names: ["nivolumab", "nivo"] },
  { slug: "ipilimumab", name: "Ipilimumab", brand: "Yervoy", group: "immune", names: ["ipilimumab", "ipi"] },
  { slug: "dostarlimab", name: "Dostarlimab", brand: "Jemperli", group: "immune", names: ["dostarlimab"] },
  { slug: "atezolizumab", name: "Atezolizumab", brand: "Tecentriq", group: "immune", names: ["atezolizumab"] },
  { slug: "sintilimab", name: "Sintilimab", group: "immune", names: ["sintilimab"] },
  { slug: "botensilimab", name: "Botensilimab", group: "immune", names: ["botensilimab"], abbreviations: ["BOT"] },
  { slug: "balstilimab", name: "Balstilimab", group: "immune", names: ["balstilimab"], abbreviations: ["BAL"] },
  { slug: "trifluridine-tipiracil", name: "Trifluridine/tipiracil", brand: "Lonsurf", group: "oral-chemo", names: ["trifluridine(?:/tipiracil)?"], abbreviations: ["TAS-102", "FTD-TPI", "FTD/TPI"] },
  { slug: "ifebemtinib", name: "Ifebemtinib", group: "other", names: ["ifebemtinib"] },
];

// A whole word: no letter on either side, so "Rego160" and "bev/RAM" match but "program" and "SEC" do not.
const word = (source: string, flags: string) =>
  new RegExp(`(?<![A-Za-z])(?:${source})(?![A-Za-z])`, flags);

const PATTERNS = new Map(
  DRUGS.map((drug) => [
    drug.slug,
    [
      ...drug.names.map((source) => word(source, "i")),
      ...(drug.abbreviations ?? []).map((source) => word(source, "")),
    ],
  ]),
);

type Named = Pick<Paper, "regimen" | "summary">;

const textOf = (paper: Named) =>
  [paper.regimen, paper.summary?.title, paper.summary?.comparison]
    .filter(Boolean)
    .join("\n");

export const names = (drug: Drug, text: string) =>
  (PATTERNS.get(drug.slug) ?? []).some((pattern) => pattern.test(text));

export const drugsOf = (paper: Named) =>
  DRUGS.filter((drug) => names(drug, textOf(paper)));

export const papersOf = <P extends Named>(drug: Drug, papers: readonly P[]) =>
  papers.filter((paper) => names(drug, textOf(paper)));

/** Drugs that at least one paper names, most papers first, then by name. */
export const drugCounts = (papers: readonly Named[]) =>
  DRUGS.map((drug) => ({ drug, count: papersOf(drug, papers).length }))
    .filter((row) => row.count > 0)
    .sort(
      (a, b) => b.count - a.count || a.drug.name.localeCompare(b.drug.name),
    );

export const drugBySlug = (slug: string) => DRUGS.find((d) => d.slug === slug);

/** A drug by its brand as typed in a URL (/drugs/stivarga/), so the page can redirect to the generic name. */
export const drugByBrand = (slug: string) =>
  DRUGS.find((d) => d.brand?.toLowerCase() === slug.toLowerCase());

/** A drug's evidence as a history: oldest publication first, then the order the site took them in. */
export const evidenceOrder = <P extends Pick<Paper, "year">>(
  papers: readonly P[],
) => [...papers].sort((a, b) => a.year - b.year); // sort is stable: same-year papers keep the site's order

export const drugPath = (drug: Pick<Drug, "slug">) => `/drugs/${drug.slug}/`;

export const DRUG_CRUMBS: Crumbs = [...HOME, ["藥物", "/drugs/"]];
