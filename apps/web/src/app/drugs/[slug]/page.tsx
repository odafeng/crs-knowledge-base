import type { Metadata } from "next";
import { notFound, permanentRedirect } from "next/navigation";
import { DrugEvidence } from "@/components/drug-evidence";
import { Breadcrumb, JsonLd } from "@/components/reading";
import { listPapers, listTopics } from "@/lib/content";
import {
  DRUG_CRUMBS,
  DRUG_GROUPS,
  drugByBrand,
  drugBySlug,
  drugPath,
  evidenceOrder,
  papersOf,
} from "@/lib/drugs";
import { pageJsonLd, pageMetadata } from "@/lib/seo";

export const revalidate = 300;
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ slug: string }> };

const leadOf = (name: string, count: number) =>
  `提到 ${name} 的研究共 ${count} 篇，依發表年份由舊到新排列，每篇附上速覽。`;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const drug = drugBySlug((await params).slug);
  if (!drug) return {};
  const count = papersOf(drug, await listPapers()).length;
  return pageMetadata(drug.name, leadOf(drug.name, count), drugPath(drug));
}

export default async function DrugPage({ params }: Props) {
  const { slug } = await params;
  const drug = drugBySlug(slug);
  if (!drug) {
    // /drugs/stivarga/ is how a surgeon may type it; the page lives under the generic name.
    const branded = drugByBrand(slug);
    if (branded) permanentRedirect(drugPath(branded));
    notFound();
  }
  const [papers, topics] = await Promise.all([listPapers(), listTopics()]);
  const mine = evidenceOrder(papersOf(drug, papers));
  const topicOf = (key: string) => topics.find((t) => t.key === key);
  const group = DRUG_GROUPS.find(([g]) => g === drug.group)?.[1];
  const crumbs = [...DRUG_CRUMBS, [drug.name, drugPath(drug)] as const];
  const lead = leadOf(drug.name, mine.length);
  return (
    <div className="container page">
      <JsonLd data={pageJsonLd(drug.name, lead, drugPath(drug), crumbs)} />
      <Breadcrumb crumbs={crumbs} />
      <header className="page-head">
        <p className="eyebrow">
          <span>{group}</span>
          {drug.brand && <span>{drug.brand}</span>}
        </p>
        <h1>{drug.name}</h1>
        <p className="page-head__lead">{lead}</p>
        {mine.some((p) => p.summary) && (
          <p className="evidence__note">
            速覽由 AI 依 PubMed 摘要整理，數字都已對過原文；標「AI
            未審」的還沒經過人工審核，解讀請以原文為準。
          </p>
        )}
      </header>
      {mine.length > 0 ? (
        <DrugEvidence papers={mine} topicOf={topicOf} />
      ) : (
        <p className="page__section">站上目前還沒有提到這個藥的研究。</p>
      )}
    </div>
  );
}
