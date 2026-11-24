import { afterEach, describe, expect, it, vi } from "vitest";
import {
  feeds,
  FEED_TAG,
  robots,
  sitemapPages,
  stream,
  toAtom,
  toJsonFeed,
  toRss,
} from "./seo";
import type { News, Paper, Topic } from "./site";

const paper = (id: string, review?: "auto" | "accepted"): Paper => ({
  id,
  slug: id.toLowerCase().replace(/_/g, "-"),
  topic: "mCRC-MSI-H",
  year: 2025,
  journal: "NEJM",
  studyType: "Phase 3 RCT",
  regimen: "Pembro & chemo",
  endpoint: "OS",
  result: "HR 0.5",
  bottomLine: "Better <now>",
  relations: [],
  source: "curated",
  reviewedAt: "2026-03-01",
  detailHtml: "",
  ...(review ? { review: { status: review, publishedAt: "2026-02-01" } } : {}),
  commentary: [
    {
      doi: "10.1/x",
      title: "Editorial",
      journal: "Lancet",
      year: 2026,
      type: "Editorial",
      summary: "A view",
      critique: false,
      newData: false,
      addedAt: "2026-02-15",
    },
  ],
});
const story: News = {
  id: "keynote",
  paperId: "KEYNOTE_177",
  publishedAt: "2026-02-15",
  headline: ["KEYNOTE：", "OS 延長"],
  dek: "摘要",
  key: { label: "OS", value: "1", unit: "" },
  figures: [],
  body: [],
  review: { status: "auto" },
};
const topics = [
  {
    key: "mCRC-MSI-H",
    slug: "msi-h",
    label: "MSI-H / dMMR",
    title: "MSI-H",
    roboticSections: [],
  },
] as unknown as Topic[];

afterEach(() => vi.unstubAllEnvs());

describe("feeds keep the current site's identifiers", () => {
  it("never changes the GUID prefix or the item IDs", () => {
    expect(FEED_TAG).toBe("tag:odafeng.github.io,2026");
    expect(stream([paper("KEYNOTE_177")], [story]).map((u) => u.id)).toEqual([
      "paper/keynote-177", // dated by its review, 2026-03-01
      "news/keynote", // same day as the commentary: news comes first, as in sitegen
      "commentary/keynote-177/10.1/x",
    ]);
  });

  it("writes RSS, Atom and JSON Feed with the same IDs, links and UTC dates", () => {
    const [all] = feeds([paper("KEYNOTE_177")], [story], topics);
    const rss = toRss(all, topics);
    expect(rss).toContain(
      '<guid isPermaLink="false">tag:odafeng.github.io,2026:paper/keynote-177</guid>',
    );
    expect(rss).toContain(
      "<link>https://odafeng.github.io/crs-knowledge-base/news/keynote/</link>",
    );
    expect(rss).toContain("<pubDate>Sun, 15 Feb 2026 00:00:00 GMT</pubDate>");
    expect(rss).toContain("<title>Pembro &amp; chemo（NEJM 2025）</title>");
    expect(rss).toContain(
      "<description>HR 0.5。Better &lt;now&gt;</description>",
    );
    expect(rss).toContain("<category>Phase 3 RCT</category>");
    const atom = toAtom({ ...all, path: "/atom.xml" }, topics);
    expect(atom).toContain("<id>tag:odafeng.github.io,2026:feed/atom.xml</id>");
    expect(atom).toContain("<updated>2026-03-01T00:00:00+00:00</updated>"); // paper re-reviewed after publishing
    const json = JSON.parse(toJsonFeed({ ...all, path: "/feed.json" }, topics));
    expect(json.items.map((i: { id: string }) => i.id)).toEqual(
      rss.match(/tag:odafeng\.github\.io,2026:[^<]+(?=<\/guid>)/g),
    );
  });

  it("publishes the news feed and one feed per topic with content, at most 30 items", () => {
    const many = Array.from({ length: 40 }, (_, i) => ({
      ...paper(`P${i}`),
      commentary: [],
    }));
    const list = feeds(many, [], topics);
    expect(list.map((f) => f.path)).toEqual(["/rss.xml", "/feed/msi-h.xml"]);
    expect(list[0].items).toHaveLength(30);

    const roboticTopic = {
      key: "robotic-surgery",
      slug: "robotic",
      label: "機器手臂手術",
      title: "機器手臂手術",
      roboticSections: [{ slug: "tme" }],
    } as unknown as Topic;
    const roboticPaper: Paper = {
      ...paper("REAL_2026"),
      topic: "robotic-surgery",
      commentary: [],
    };
    const withSurgery = feeds([roboticPaper], [], [...topics, roboticTopic]);
    expect(withSurgery.map((f) => f.path)).toEqual([
      "/rss.xml",
      "/feed/robotic.xml",
    ]);
    const pages = sitemapPages([roboticPaper], [], [...topics, roboticTopic]);
    expect(pages).toContainEqual(["/robotic/", "2026-03-01"]);
  });

  it("follows the configured origin for links but not for IDs", () => {
    vi.stubEnv("GUTHUB_SITE_ORIGIN", "https://guthub.example/");
    const rss = toRss(feeds([paper("KEYNOTE_177")], [], topics)[0], topics);
    expect(rss).toContain(
      "<link>https://guthub.example/papers/keynote-177/</link>",
    );
    expect(rss).toContain("tag:odafeng.github.io,2026:paper/keynote-177");
  });
});

describe("indexing", () => {
  it("keeps everything out of search engines until the site is public", () => {
    expect(robots(true)).toEqual({ index: false, follow: false });
    vi.stubEnv("GUTHUB_SITE_PUBLIC", "1");
    expect(robots(true)).toEqual({ index: true, follow: true });
    expect(robots(false)).toEqual({ index: false, follow: true });
  });

  it("leaves AI-unreviewed papers and news out of the sitemap", () => {
    const pages = sitemapPages(
      [paper("A", "auto"), paper("B", "accepted")],
      [story],
      topics,
    ).map(([path]) => path);
    expect(pages).toContain("/papers/b/");
    expect(pages).not.toContain("/papers/a/");
    expect(pages).not.toContain("/news/keynote/");
    expect(pages.slice(0, 3)).toEqual(["/", "/news/", "/updates/"]);
  });
});
