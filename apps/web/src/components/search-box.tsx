"use client";

// Search over /search.json in the browser, as search.js does on the current site.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/reading";
import { findEntries, type SearchEntry } from "@/lib/search";

let indexRequest: Promise<SearchEntry[]> | null = null;

function loadIndex(): Promise<SearchEntry[]> {
  if (!indexRequest) {
    indexRequest = fetch("/search.json").then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json() as Promise<SearchEntry[]>;
    });
    // A failed load may succeed later (back online), so it is not remembered.
    indexRequest.catch(() => {
      indexRequest = null;
    });
  }
  return indexRequest;
}

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "done"; hits: SearchEntry[] };

export function SearchBox() {
  const input = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<State>({ kind: "idle" });

  useEffect(() => {
    if (location.hash === "#q") input.current?.focus();
  }, []);

  async function search(query: string) {
    if (findEntries([], query) === null) return setState({ kind: "idle" });
    setState((s) => (s.kind === "done" ? s : { kind: "loading" }));
    try {
      const index = await loadIndex();
      // Ignore answers to queries the reader has already typed past.
      if (input.current?.value !== query) return;
      setState({ kind: "done", hits: findEntries(index, query) ?? [] });
    } catch {
      if (input.current?.value === query) setState({ kind: "error" });
    }
  }

  return (
    <>
      <form
        className="search"
        role="search"
        onSubmit={(event) => event.preventDefault()}
      >
        <label className="visually-hidden" htmlFor="q">
          搜尋消息與文獻
        </label>
        <Icon name="search" />
        <input
          ref={input}
          id="q"
          type="search"
          name="q"
          placeholder="搜尋試驗、藥物、biomarker（例：NICHE、dostarlimab）"
          autoComplete="off"
          onChange={(event) => search(event.target.value)}
        />
      </form>
      <div id="search-results" className="search-results" aria-live="polite">
        {state.kind === "loading" && <p>搜尋中…</p>}
        {state.kind === "error" && (
          <p>無法載入搜尋資料，請確認網路連線後再輸入一次。</p>
        )}
        {state.kind === "done" && (
          <>
            <p>
              {state.hits.length
                ? `找到 ${state.hits.length} 筆`
                : "找不到符合的消息或文獻"}
            </p>
            <ul>
              {state.hits.slice(0, 8).map((hit) => (
                <li key={hit.path}>
                  <Link href={hit.path}>{hit.title}</Link>
                  <span>{hit.meta}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </>
  );
}
