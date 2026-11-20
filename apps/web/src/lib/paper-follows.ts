// Following papers for the daily comment digest (G8 #119, ADR-0022). What a reader follows lives behind
// GET /me/follows and never in a shared page; the digest's unsubscribe links work without signing in.
import { apiFetch, apiUrl } from "./auth";

export type Follows = { papers: string[]; commentDigest: boolean };
export type FollowedPaper = { id: string; title: string; path: string };

/** The followed papers that are still public, in the order the API gives (newest follow first). */
export function followedPapers(
  ids: string[],
  papers: FollowedPaper[],
): FollowedPaper[] {
  const byId = new Map(papers.map((paper) => [paper.id, paper]));
  return ids.flatMap((id) => byId.get(id) ?? []);
}

async function state(response: Promise<Response>): Promise<Follows | null> {
  const answer = await response.catch(() => null);
  return answer?.ok ? ((await answer.json()) as Follows) : null;
}

export const loadFollows = (token: string) =>
  state(apiFetch("/me/follows", token));

export const setFollow = (token: string, paperId: string, on: boolean) =>
  state(
    apiFetch(`/me/follows/${encodeURIComponent(paperId)}`, token, {
      method: on ? "PUT" : "DELETE",
    }),
  );

export const setDigest = (token: string, enabled: boolean) =>
  state(
    apiFetch("/me/comment-digest", token, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  );

/** From a digest's link: unfollow `paper`, or stop the digest. "unknown" when the link is not (or no longer) valid. */
export async function unsubscribe(
  token: string,
  paper: string | null,
): Promise<"done" | "unknown" | "failed"> {
  const query = new URLSearchParams({ token });
  if (paper) query.set("paper", paper);
  const response = await fetch(apiUrl(`/digest/unsubscribe?${query}`), {
    method: "POST",
    credentials: "omit",
    cache: "no-store",
  }).catch(() => null);
  if (response?.status === 204) return "done";
  if (response?.status === 404 || response?.status === 422) return "unknown";
  return "failed";
}
