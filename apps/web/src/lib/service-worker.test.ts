// Runs the real public/sw.js in a VM with an in-memory CacheStorage and a scripted network.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { beforeEach, describe, expect, it } from "vitest";

const ORIGIN = "https://guthub.test";
const SOURCE = readFileSync(
  fileURLToPath(new URL("../../public/sw.js", import.meta.url)),
  "utf8",
);

class MemoryCache {
  entries = new Map<string, Response>();
  async match(request: Request | string) {
    return this.entries.get(url(request))?.clone();
  }
  async put(request: Request | string, response: Response) {
    this.entries.set(url(request), response);
  }
  async delete(request: Request | string) {
    return this.entries.delete(url(request));
  }
  async keys() {
    return [...this.entries.keys()].map((key) => new Request(key));
  }
}
const url = (request: Request | string) =>
  new URL(typeof request === "string" ? request : request.url, ORIGIN).href;

type Route = { status?: number; body?: string; headers?: HeadersInit };

function html(...assets: string[]): Route {
  return {
    body: `<html><head>${assets.map((a) => `<link href="${a}">`).join("")}</head></html>`,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  };
}

function setup() {
  const caches = new Map<string, MemoryCache>();
  const routes = new Map<string, Route>();
  let online = true;
  const requested: string[] = [];
  const listeners: Record<string, (event: unknown) => void> = {};
  const fetch = async (input: Request | string) => {
    const target = url(input);
    requested.push(new URL(target).pathname);
    if (!online) throw new TypeError("Failed to fetch");
    const route = routes.get(new URL(target).pathname) ?? { status: 404 };
    return new Response(route.body ?? "", {
      status: route.status ?? 200,
      headers: route.headers,
    });
  };
  const self = {
    location: new URL(ORIGIN),
    addEventListener: (type: string, fn: (event: unknown) => void) =>
      (listeners[type] = fn),
    skipWaiting: async () => {},
    clients: { claim: async () => {} },
  };
  vm.runInNewContext(SOURCE, {
    self,
    fetch,
    URL,
    Request,
    Response,
    Set,
    Date,
    caches: {
      open: async (name: string) => {
        if (!caches.has(name)) caches.set(name, new MemoryCache());
        return caches.get(name)!;
      },
      keys: async () => [...caches.keys()],
      delete: async (name: string) => caches.delete(name),
    },
  });

  async function extendable(type: string, extra: object = {}) {
    let pending: Promise<unknown> = Promise.resolve();
    listeners[type]({
      ...extra,
      waitUntil: (p: Promise<unknown>) => (pending = p),
    });
    await pending;
  }

  return {
    caches,
    routes,
    requested,
    setOnline: (value: boolean) => (online = value),
    cache: () => caches.get("guthub-public-v1")!,
    cached: (path: string) =>
      caches.get("guthub-public-v1")?.entries.has(`${ORIGIN}${path}`) ?? false,
    install: () => extendable("install"),
    activate: () => extendable("activate"),
    sync: (force = true) =>
      extendable("message", { data: { type: "sync", force } }),
    /** Dispatches a fetch event; resolves to the response, or null when the worker leaves it to the browser. */
    async get(path: string, init: RequestInit = {}) {
      let answer = null as Promise<Response> | null;
      listeners.fetch({
        request: new Request(new URL(path, ORIGIN), init),
        respondWith: (p: Promise<Response>) => (answer = p),
      });
      return answer;
    },
  };
}

const index = (...paths: string[]): Route => ({
  body: JSON.stringify(
    paths.map((path) => ({ path, title: path, meta: "", text: path })),
  ),
  headers: { "Content-Type": "application/json" },
});

describe("service worker", () => {
  let sw: ReturnType<typeof setup>;
  beforeEach(() => {
    sw = setup();
    sw.routes.set("/", html("/_next/static/css/app.css"));
    sw.routes.set("/_next/static/css/app.css", { body: "body{}" });
    sw.routes.set("/papers/niche2/", html("/_next/static/chunks/paper.js"));
    sw.routes.set("/_next/static/chunks/paper.js", { body: "" });
    sw.routes.set("/news/niche2-five-year/", html());
    sw.routes.set(
      "/search.json",
      index("/papers/niche2/", "/news/niche2-five-year/"),
    );
  });

  it("installs the shell pages with the assets they reference", async () => {
    await sw.install();
    expect(sw.cached("/")).toBe(true);
    expect(sw.cached("/_next/static/css/app.css")).toBe(true);
  });

  it("stores every public page in the index so it opens offline", async () => {
    await sw.sync();
    expect(sw.cached("/search.json")).toBe(true);
    expect(sw.cached("/papers/niche2/")).toBe(true);
    expect(sw.cached("/_next/static/chunks/paper.js")).toBe(true);

    sw.setOnline(false);
    const page = await sw.get("/papers/niche2/?utm_source=x");
    expect(await page?.text()).toContain("paper.js");
    const search = await sw.get("/search.json");
    expect(await search?.json()).toHaveLength(2);
  });

  it("drops a withdrawn paper on the next sync", async () => {
    await sw.sync();
    sw.routes.set("/search.json", index("/news/niche2-five-year/"));
    sw.routes.delete("/papers/niche2/");
    await sw.sync();
    expect(sw.cached("/papers/niche2/")).toBe(false);
    expect(sw.cached("/news/niche2-five-year/")).toBe(true);

    sw.setOnline(false);
    expect((await sw.get("/papers/niche2/"))?.type).toBe("error");
  });

  it("drops a cached page as soon as the server answers 404 or 410", async () => {
    await sw.sync();
    sw.routes.set("/papers/niche2/", { status: 410 });
    const response = await sw.get("/papers/niche2/");
    expect(response?.status).toBe(410);
    expect(sw.cached("/papers/niche2/")).toBe(false);
  });

  it("serves the network copy first, so updates show while online", async () => {
    await sw.sync();
    sw.routes.set("/papers/niche2/", html("/_next/static/chunks/v2.js"));
    expect(await (await sw.get("/papers/niche2/"))?.text()).toContain("v2.js");
  });

  it("drops build assets that no stored page or stylesheet references", async () => {
    sw.routes.set("/_next/static/css/app.css", {
      body: "@font-face{src:url(../media/noto.woff2)}",
    });
    sw.routes.set("/_next/static/media/noto.woff2", { body: "" });
    await sw.install();
    await sw.get("/_next/static/media/noto.woff2");
    await sw
      .cache()
      .put(`${ORIGIN}/_next/static/chunks/old-build.js`, new Response(""));
    await sw.sync();
    expect(sw.cached("/_next/static/chunks/old-build.js")).toBe(false);
    expect(sw.cached("/_next/static/css/app.css")).toBe(true);
    expect(sw.cached("/_next/static/media/noto.woff2")).toBe(true);
    expect(sw.cached("/_next/static/chunks/paper.js")).toBe(true);
  });

  it("does not repeat a sync within ten minutes unless forced", async () => {
    await sw.sync(false);
    const count = sw.requested.length;
    await sw.sync(false);
    expect(sw.requested.length).toBe(count);
  });

  it.each([
    ["/api/v1/me", {}],
    ["/auth/callback?code=x", {}],
    ["/me/", {}],
    ["/account/", {}],
    ["/admin/comments/", {}],
    ["/papers/niche2/", { headers: { Authorization: "Bearer t" } }],
    ["/papers/niche2/", { headers: { RSC: "1" } }],
    ["/papers/niche2/?_rsc=abc", {}],
    ["/papers/niche2/comments", { method: "POST", body: "{}" }],
    ["https://cdn.example/x.js", {}],
  ] as const)("leaves %s to the browser", async (path, init) => {
    expect(await sw.get(path, init as RequestInit)).toBeNull();
  });

  it("never stores responses marked private or no-store", async () => {
    for (const control of ["private, max-age=0", "no-store"]) {
      sw.routes.set("/updates/", {
        ...html(),
        headers: { "Content-Type": "text/html", "Cache-Control": control },
      });
      await sw.get("/updates/");
      expect(sw.cached("/updates/")).toBe(false);
    }
  });

  it("clears older caches, including the current site's, on activate", async () => {
    sw.caches.set("seminar-hegemon-59e05d21907ff017", new MemoryCache());
    sw.caches.set("guthub-public-v0", new MemoryCache());
    sw.caches.set("unrelated", new MemoryCache());
    await sw.install();
    await sw.activate();
    expect([...sw.caches.keys()].sort()).toEqual([
      "guthub-public-v1",
      "unrelated",
    ]);
  });
});
