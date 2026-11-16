import type { components } from "./api.generated";

export type Paper = components["schemas"]["Paper"];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOptions = { baseUrl?: string; fetcher?: typeof fetch };

export async function getPaper(
  paperId: string,
  { baseUrl = "/api/v1", fetcher = fetch }: RequestOptions = {},
): Promise<Paper> {
  const response = await fetcher(
    `${baseUrl.replace(/\/$/, "")}/papers/${encodeURIComponent(paperId)}`,
    {
      cache: "no-store",
      headers: { accept: "application/json" },
    },
  );
  if (!response.ok) {
    throw await apiError(response, "無法載入文獻，請稍後再試。");
  }
  return response.json() as Promise<Paper>;
}

/** Turns a failed response into an ApiError, keeping the contract's error message when the body has one. */
export async function apiError(
  response: Response,
  fallback: string,
): Promise<ApiError> {
  let message = fallback;
  let code: string | undefined;
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && "error" in payload) {
      const error = payload.error;
      if (
        error &&
        typeof error === "object" &&
        "message" in error &&
        typeof error.message === "string"
      ) {
        message = error.message;
        if ("code" in error && typeof error.code === "string")
          code = error.code;
      }
    }
  } catch {
    // A proxy or unavailable server may return HTML instead of the API error envelope.
  }
  return new ApiError(response.status, message, code);
}
