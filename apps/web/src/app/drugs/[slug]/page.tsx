import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Breadcrumb, Entry, JsonLd } from "@/components/reading";
import { listPapers, listTopics } from "@/lib/content";
import {
  DRUG_CRUMBS,
  DRUG_GROUPS,
  drugBySlug,
  drugPath,
  papersOf,
} from "@/lib/drugs";
import { pageJsonLd, pageMetadata } from "@/lib/seo";
import { updates } from "@/lib/site";

export const revalidate = 300;
export async function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ slug: string }> };

const leadOf = (name: string, count: number) =>
  `提到 ${name} 的文獻共 ${count} 篇，新的在前。`;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const drug = drugBySlug((await params).slug);
  if (!drug) return {};
  const count = papersOf(drug, await listPapers()).length;
  return pageMetadata(drug.name, leadOf(drug.name, count), drugPath(drug));
}

export default async function DrugPage({ params }: Props) {
  const drug = drugBySlug((await params).slug);
  if (!drug) notFound();
  const [papers, topics] = await Promise.all([listPapers(), listTopics()]);
  const mine = papersOf(drug, papers);
  const rows = updates(mine);
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
      </header>
      {rows.length > 0 ? (
        <ol className="entries entries--grid page__section">
          {rows.map((update) => (
            <Entry
              update={update}
              topic={topicOf(update.paper.topic)}
              level={2}
              key={update.id}
            />
          ))}
        </ol>
      ) : (
        <p className="page__section">站上目前還沒有提到這個藥的文獻。</p>
      )}
    </div>
  );
}
