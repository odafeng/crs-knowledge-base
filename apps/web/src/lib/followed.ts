// Followed topics (G6 #117). The list lives behind GET /me/topics; pages ship every public update, and the reader's
// browser picks the followed ones, so no shared page or cache ever holds what someone follows.
import { apiFetch } from "./auth";

export type FollowRow = {
  path: string;
  title: string;
  date: string;
  topic: string;
  topicLabel: string;
};

export function followedUpdates(
  rows: FollowRow[],
  topics: string[],
  limit: number,
): FollowRow[] {
  const chosen = new Set(topics);
  return rows
    .filter((row) => chosen.has(row.topic))
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
