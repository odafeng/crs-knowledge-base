// GutHub brand settings (C4 #66): display name only; URLs, feed IDs and PWA scope stay as decided in A3 #55.
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import manifest from "../app/manifest";
import { pageMetadata, SHARE_IMAGE, siteOrigin } from "./seo";

const publicFile = (path: string) =>
  fileURLToPath(new URL(`../../public/${path}`, import.meta.url));

describe("web app manifest", () => {
  const m = manifest();

  it("uses the GutHub display name", () => {
    expect(m.name).toBe("GutHub｜大腸直腸外科實證更新");
    expect(m.short_name).toBe("GutHub");
    expect(m.lang).toBe("zh-Hant-TW");
  });

  it("keeps start_url and scope relative, so a later origin or base path needs no change", () => {
    expect(m.start_url).toBe("./");
    expect(m.scope).toBe("./");
    expect(m.display).toBe("standalone");
  });

  it("points only at icons that exist, including a maskable one", () => {
    expect(m.icons?.length).toBe(3);
    for (const icon of m.icons ?? [])
      expect(existsSync(publicFile(icon.src))).toBe(true);
    expect(m.icons?.some((icon) => icon.purpose === "maskable")).toBe(true);
  });
});

describe("share metadata", () => {
  it("gives every page the same share image and card as the current site", () => {
    const meta = pageMetadata("BEACON", "desc", "/papers/beacon/");
    expect(meta.openGraph?.images).toEqual([`${siteOrigin()}${SHARE_IMAGE}`]);
    expect(meta.twitter).toEqual({ card: "summary_large_image" });
    expect(existsSync(publicFile(SHARE_IMAGE.slice(1)))).toBe(true);
  });
});
