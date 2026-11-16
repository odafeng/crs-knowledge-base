import type { MetadataRoute } from "next";
import { SITE_NAME, TAGLINE } from "@/lib/seo";

// Same as sitegen's manifest (render.py _manifest) apart from the name; tools/check_next_parity.py compares them.
// start_url and scope stay relative to the manifest, so they keep working if the site later moves to another
// origin or base path (A3 #55).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${SITE_NAME}｜${TAGLINE}`,
    short_name: SITE_NAME,
    lang: "zh-Hant-TW",
    start_url: "./",
    scope: "./",
    display: "standalone",
    background_color: "#F3F5FB",
    theme_color: "#0E2270",
    icons: [
      { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
      {
        src: "icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
