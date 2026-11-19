import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";
import { Breadcrumb, JsonLd } from "@/components/reading";
import { listPapers } from "@/lib/content";
import { DRUG_CRUMBS, DRUG_GROUPS, drugCounts, drugPath } from "@/lib/drugs";
import { pageJsonLd, pageMetadata } from "@/lib/seo";

const LEAD = "依藥物找文獻：試驗用藥、對照組與前線用過的藥都算在內。";

export const metadata: Metadata = pageMetadata("藥物", LEAD, "/drugs/");

export default async function DrugsPage() {
  // Rendered per request so `next build` never calls the API; API reads stay cached for 300 s (lib/content.ts).
  await connection();
  const counts = drugCounts(await listPapers());
  return (
    <div className="container page">
      <JsonLd data={pageJsonLd("藥物", LEAD, "/drugs/", DRUG_CRUMBS)} />
      <Breadcrumb crumbs={DRUG_CRUMBS} />
      <header className="page-head">
        <h1>藥物</h1>
        <p className="page-head__lead">{LEAD}</p>
      </header>
      {DRUG_GROUPS.map(([group, label]) => {
        const rows = counts
          .filter((row) => row.drug.group === group)
          .sort((a, b) => a.drug.name.localeCompare(b.drug.name));
        if (rows.length === 0) return null;
        return (
          <section
            className="page__section"
            aria-labelledby={`drugs-${group}`}
            key={group}
          >
            <h2 id={`drugs-${group}`}>{label}</h2>
            <ul className="tile-grid">
              {rows.map(({ drug, count }) => (
                <li className="tile" key={drug.slug}>
                  <p className="tile__count">
                    <span className="num">{count}</span>篇文獻
                  </p>
                  <h3 className="tile__title">
                    <Link href={drugPath(drug)}>{drug.name}</Link>
                  </h3>
                  {drug.brand && <p className="tile__text">{drug.brand}</p>}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
