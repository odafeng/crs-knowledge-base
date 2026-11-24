// On-demand ISR / Data Cache revalidation handler (K3 #253).
// Protected by a shared Bearer secret (GUTHUB_REVALIDATE_SECRET) verified in constant time.
import { createHash, timingSafeEqual } from "node:crypto";
import { CONTENT_TAG } from "./content";

const ALLOWED_TAG =
  /^(guthub-content|papers|news|topics|daily|(?:paper|news):[a-z0-9][a-z0-9-]*)$/;
const ALLOWED_PATH = /^\/[a-z0-9/_-]*\/?$/;
const MAX_ITEMS = 20;
const NO_STORE = { "Cache-Control": "no-store" };

export type RevalidateOps = {
  revalidateTag: (tag: string, profile: { expire: number }) => void;
  revalidatePath: (path: string) => void;
};

function secretMatches(provided: string, expected: string): boolean {
  // Hash both sides to fixed 32-byte digests so timingSafeEqual never leaks secret length.
  const a = createHash("sha256").update(provided).digest();
  const b = createHash("sha256").update(expected).digest();
  return timingSafeEqual(a, b);
}

function bearerToken(header: string | null): string | null {
  if (!header) return null;
  const match = header.match(/^Bearer\s+(\S+)$/i);
  return match ? match[1] : null;
}

function parseList(
  value: unknown,
  pattern: RegExp,
  name: string,
): { items: string[]; error?: string } {
  if (value === undefined) return { items: [] };
  if (!Array.isArray(value) || value.length > MAX_ITEMS) {
    return {
      items: [],
      error: `${name} must be an array of at most ${MAX_ITEMS} items`,
    };
  }
  const items: string[] = [];
  for (const item of value) {
    if (typeof item !== "string" || !pattern.test(item)) {
      return { items: [], error: `invalid ${name} entry` };
    }
    if (!items.includes(item)) items.push(item);
  }
  return { items };
}

export async function handleRevalidate(
  request: Request,
  ops: RevalidateOps,
  secret = process.env.GUTHUB_REVALIDATE_SECRET,
): Promise<Response> {
  const expected = secret?.trim() ?? "";
  if (!expected) {
    return Response.json(
      { error: "Revalidation is not configured" },
      { status: 503, headers: NO_STORE },
    );
  }
  const token = bearerToken(request.headers.get("authorization"));
  if (!token || !secretMatches(token, expected)) {
    return Response.json(
      { error: "Unauthorized" },
      { status: 401, headers: NO_STORE },
    );
  }

  let body: Record<string, unknown> = {};
  const raw = (await request.text()).trim();
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return Response.json(
          { error: "Body must be a JSON object" },
          { status: 400, headers: NO_STORE },
        );
      }
      body = parsed as Record<string, unknown>;
    } catch {
      return Response.json(
        { error: "Invalid JSON body" },
        { status: 400, headers: NO_STORE },
      );
    }
  }

  const parsedTags = parseList(body.tags, ALLOWED_TAG, "tags");
  if (parsedTags.error) {
    return Response.json(
      { error: parsedTags.error },
      { status: 400, headers: NO_STORE },
    );
  }
  const parsedPaths = parseList(body.paths, ALLOWED_PATH, "paths");
  if (parsedPaths.error) {
    return Response.json(
      { error: parsedPaths.error },
      { status: 400, headers: NO_STORE },
    );
  }

  const tags =
    parsedTags.items.length === 0 && parsedPaths.items.length === 0
      ? [CONTENT_TAG]
      : parsedTags.items;
  const paths = parsedPaths.items;

  for (const tag of tags) ops.revalidateTag(tag, { expire: 0 });
  for (const path of paths) ops.revalidatePath(path);

  return Response.json(
    { revalidated: true, tags, paths },
    { status: 200, headers: NO_STORE },
  );
}
