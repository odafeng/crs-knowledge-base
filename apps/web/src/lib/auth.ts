// Sign-in for readers (D1 #67, ADR-0020). The Supabase session lives only in this browser (localStorage); pages are
// rendered without it, so shared HTML, the CDN and the service worker never hold anyone's identity. The FastAPI
// service receives the access token as a bearer header and never reads cookies.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

/** Sign-in is offered only when the build knows the Supabase project and the API. */
export const authEnabled = Boolean(
  SUPABASE_URL && SUPABASE_KEY && process.env.NEXT_PUBLIC_GUTHUB_API_URL,
);
/** Google needs an OAuth client (F1 #75); until then only the email link is shown. */
export const googleEnabled =
  authEnabled && process.env.NEXT_PUBLIC_AUTH_GOOGLE === "1";

let client: SupabaseClient | null = null;

export function supabase(): SupabaseClient {
  if (!authEnabled) throw new Error("Sign-in is not configured");
  client ??= createClient(SUPABASE_URL!, SUPABASE_KEY!, {
    auth: {
      flowType: "pkce",
      persistSession: true,
      autoRefreshToken: true,
      // /auth/callback/ and /auth/confirm/ finish sign-in explicitly; other pages never read tokens from the URL.
      detectSessionInUrl: false,
    },
  });
  return client;
}

/** Calls the GutHub API as the signed-in reader. */
export function apiFetch(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<Response> {
  const base = (process.env.NEXT_PUBLIC_GUTHUB_API_URL ?? "").replace(
    /\/$/,
    "",
  );
  return fetch(`${base}${path}`, {
    ...init,
    credentials: "omit",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });
}

const NO_RETURN = /^\/(auth|login)(\/|$)/;

const PARSE_BASE = "https://guthub.invalid";

/**
 * Where to go after signing in: a path on this site, never another origin or the sign-in pages themselves.
 * Parsed the way the browser will parse it (which drops tabs and newlines, so "/\t/evil" means "//evil").
 */
export function safeNext(next: string | null | undefined): string {
  if (!next?.startsWith("/")) return "/";
  let url: URL;
  try {
    url = new URL(next, PARSE_BASE);
  } catch {
    return "/";
  }
  if (url.origin !== PARSE_BASE || NO_RETURN.test(url.pathname)) return "/";
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Same rules as the API's AccountUpdate (1-80 characters after trimming, no control characters). */
export function displayNameError(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "請填寫顯示名稱";
  if (/[\u0000-\u001f\u007f]/.test(trimmed))
    return "顯示名稱不能包含換行或控制字元";
  if ([...trimmed].length > 80) return "顯示名稱最多 80 個字";
  return null;
}

/** Remembers where the reader was, for the email link that may open in a new tab or on another device. */
export const AFTER_LOGIN_KEY = "guthub:after-login";
