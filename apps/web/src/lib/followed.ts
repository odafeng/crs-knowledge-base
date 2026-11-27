// Followed topics (G6 #117). The list lives behind GET /me/topics; pages ship every public update, and the reader's
// browser picks the followed ones, so no shared page or cache ever holds what someone follows.
import { apiFetch } from "./auth";

export type FollowRow = {
  path: string;
  title: string;
  date: string;
  topic: string;
  topicLabel: string;
  domains?: string[];
};

export function followedUpdates(
  rows: FollowRow[],
  topics: string[],
  limit: number,
  domains: string[] = [],
): FollowRow[] {
  const chosenTopics = new Set(topics);
  const chosenDomains = new Set(domains);
  return rows
    .filter(
      (row) =>
        chosenTopics.has(row.topic) ||
        (row.domains ?? []).some((d) => chosenDomains.has(d)),
    )
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, limit);
}

export async function loadTopics(token: string): Promise<string[] | null> {
  const response = await apiFetch("/me/topics", token).catch(() => null);
  if (!response?.ok) return null;
  return ((await response.json()) as { topics: string[] }).topics;
}

export async function saveTopics(
  token: string,
  topics: string[],
): Promise<Response | null> {
  return apiFetch("/me/topics", token, {
    method: "PUT",
    body: JSON.stringify({ topics }),
  }).catch(() => null);
}

export async function loadDomains(token: string): Promise<string[] | null> {
  const response = await apiFetch("/me/domains", token).catch(() => null);
  if (!response?.ok) return null;
  return ((await response.json()) as { domains: string[] }).domains;
}

export async function saveDomains(
  token: string,
  domains: string[],
): Promise<Response | null> {
  return apiFetch("/me/domains", token, {
    method: "PUT",
    body: JSON.stringify({ domains }),
  }).catch(() => null);
}
