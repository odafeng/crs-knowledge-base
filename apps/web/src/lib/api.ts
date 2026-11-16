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
    let message = "無法載入文獻，請稍後再試。";
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
    throw new ApiError(response.status, message, code);
  }
  return response.json() as Promise<Paper>;
}
