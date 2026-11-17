// Natural-language search (H3 #125, ADR-0022): the API embeds the question and returns the closest passages from
// the site. It finds what the site already has; it never writes an answer.
import { apiUrl } from "./auth";

export type SemanticHit = {
  kind: "paper" | "news" | "card";
  path: string;
  title: string;
  snippet: string;
  score: number;
};

export type SemanticOutcome =
  { kind: "done"; hits: SemanticHit[] } | { kind: "error"; message: string };

export const KIND_LABEL: Record<SemanticHit["kind"], string> = {
  paper: "文獻",
  news: "消息",
  card: "治療整理",
};

export function outcomeOf(status: number | null, hits?: SemanticHit[]) {
  if (status === 200 && hits) return { kind: "done", hits } as const;
  const message =
    status === 422
      ? "請輸入 2 到 200 個字的問題。"
      : status === 503
        ? "語意搜尋暫時無法使用，請改用關鍵字搜尋。"
        : status === null
          ? "搜尋失敗，請檢查網路後再試一次。"
          : "暫時無法搜尋，請稍後再試。";
  return { kind: "error", message } as const;
}

export async function semanticSearch(query: string): Promise<SemanticOutcome> {
  // A public endpoint: no session, and the question goes in the body so it stays out of request logs.
  const response = await fetch(apiUrl("/semantic-search"), {
    method: "POST",
    credentials: "omit",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: query.trim() }),
  }).catch(() => null);
  if (response?.ok) {
    const body = (await response.json()) as { results: SemanticHit[] };
    return outcomeOf(200, body.results);
  }
  return outcomeOf(response?.status ?? null);
}
