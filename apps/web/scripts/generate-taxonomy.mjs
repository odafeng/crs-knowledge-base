// Generate apps/web/src/lib/taxonomy.generated.ts from contracts/taxonomy.json (T1 #282, ADR-0030).
// Usage:
//   node scripts/generate-taxonomy.mjs          # write generated file
//   node scripts/generate-taxonomy.mjs --check  # exit 1 if out of sync
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../..");
const sourcePath = resolve(root, "contracts/taxonomy.json");
const targetPath = resolve(here, "../src/lib/taxonomy.generated.ts");

const registry = JSON.parse(readFileSync(sourcePath, "utf8"));
const domainSlugs = registry.domains
  .slice()
  .sort((a, b) => a.order - b.order)
  .map((d) => d.slug);

const lines = [
  "// Auto-generated from contracts/taxonomy.json by scripts/generate-taxonomy.mjs.",
  "// Do not edit by hand; run `npm run contract:generate` after updating contracts/taxonomy.json.",
  "",
  `export const TAXONOMY_VERSION = ${JSON.stringify(registry.version)} as const;`,
  "",
  `export const DOMAIN_SLUGS = ${JSON.stringify(domainSlugs, null, 2)} as const;`,
  "",
  "export type DomainSlug = (typeof DOMAIN_SLUGS)[number];",
  "",
  "export interface TaxonomyDomain {",
  "  readonly slug: DomainSlug;",
  "  readonly order: number;",
  "  readonly labelZh: string;",
  "  readonly labelEn: string;",
  "  readonly descriptionZh: string;",
  '  readonly status: "active" | "deprecated";',
  "}",
  "",
  "export interface TaxonomySubtopic {",
  "  readonly id: string;",
  "  readonly parentDomain: DomainSlug;",
  "  readonly slug: string;",
  "  readonly labelZh: string;",
  "  readonly labelEn: string;",
  "  readonly legacyTopicKey: string | null;",
  "  readonly routePath: string | null;",
  "  readonly order: number;",
  '  readonly status: "active" | "legacy_compat" | "deprecated";',
  "}",
  "",
  `export const TAXONOMY_DOMAINS: readonly TaxonomyDomain[] = ${JSON.stringify(registry.domains, null, 2)};`,
  "",
  `export const TAXONOMY_SUBTOPICS: readonly TaxonomySubtopic[] = ${JSON.stringify(registry.subtopics, null, 2)};`,
  "",
  `export const TAXONOMY_TAGS: readonly string[] = ${JSON.stringify(registry.tags, null, 2)};`,
  "",
];

const expected = lines.join("\n");
const checkOnly = process.argv.includes("--check");

if (checkOnly) {
  let actual = "";
  try {
    actual = readFileSync(targetPath, "utf8");
  } catch {
    console.error(`Missing generated taxonomy file: ${targetPath}`);
    process.exit(1);
  }
  if (actual !== expected) {
    console.error(
      "apps/web/src/lib/taxonomy.generated.ts is out of sync with contracts/taxonomy.json. Run `npm run contract:generate`.",
    );
    process.exit(1);
  }
  process.exit(0);
}

writeFileSync(targetPath, expected, "utf8");
