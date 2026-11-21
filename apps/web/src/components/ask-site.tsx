"use client";

// The home page's natural-language search (H3 #125): one question in, the closest papers, news and treatment
// summaries out, and for verified members the closest forum threads in their own list (H8 #130). Searches on submit,
// not on every keystroke, because each query is a paid embedding.
import Link from "next/link";
import { useState } from "react";
import { useAccount } from "@/components/account";
import { Icon } from "@/components/reading";
import {
  KIND_LABEL,
  grouped,
  semanticSearch,
  type SemanticHit,
  type SemanticOutcome,
} from "@/lib/semantic";

function Hits({ hits, label }: { hits: SemanticHit[]; label: string }) {
  return (
    <ol aria-label={label}>
      {hits.map((hit) => (
        <li key={`${hit.kind}:${hit.path}:${hit.title}`}>
          <span className="ask-site__kind">{KIND_LABEL[hit.kind]}</span>
          <Link href={hit.path}>{hit.title}</Link>
          <p>{hit.snippet}</p>
        </li>
      ))}
    </ol>
  );
}

export function AskSite() {
  const account = useAccount();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<SemanticOutcome | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true);
    const token = account.status === "signed-in" ? account.token : undefined;
    setOutcome(await semanticSearch(query, token));
    setBusy(false);
  }

  return (
    <section className="ask-site" aria-labelledby="ask-site-title">
      <div className="container ask-site__bar">
        <h2 id="ask-site-title">用一句話找證據</h2>
        <div className="ask-site__body">
          <form className="ask-site__form" role="search" onSubmit={submit}>
            <label className="visually-hidden" htmlFor="ask-site-q">
              用一句話描述你的問題
            </label>
            <Icon name="search" />
            <input
              id="ask-site-q"
              type="search"
              maxLength={200}
              placeholder="例：左側 RAS 野生型的一線該選哪個生物製劑？"
              autoComplete="off"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <button className="btn btn--primary" type="submit" disabled={busy}>
              {busy ? "搜尋中…" : "搜尋"}
            </button>
          </form>
          <p className="ask-site__note">
            依語意找出站上最相關的文獻、消息與治療整理，不會產生答案。問題不會存下來。
          </p>
          <div className="ask-site__results" aria-live="polite">
            {outcome?.kind === "error" && <p>{outcome.message}</p>}
            {outcome?.kind === "done" && <Results hits={outcome.hits} />}
          </div>
        </div>
      </div>
    </section>
  );
}

function Results({ hits }: { hits: SemanticHit[] }) {
  const { evidence, forum } = grouped(hits);
  if (hits.length === 0) {
    return (
      <p>
        站上沒有和這個問題夠相關的內容。可以換個說法，或到
        <Link href="/updates/#q">關鍵字搜尋</Link>。
      </p>
    );
  }
  return (
    <>
      {evidence.length > 0 && (
        <>
          <h3 className="ask-site__group">證據</h3>
          <Hits hits={evidence} label="證據" />
        </>
      )}
      {forum.length > 0 && (
        <>
          <h3 className="ask-site__group">論壇討論</h3>
          <p className="ask-site__note">會員的個人意見，不是本站的證據整理。</p>
          <Hits hits={forum} label="論壇討論" />
        </>
      )}
    </>
  );
}
