import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { DisplaySettings } from "@/components/display-settings";
import { OfflineReading } from "@/components/offline-reading";
import { SiteHeader } from "@/components/site-header";
import { TabBar } from "@/components/site-nav";
import { PREFS_SCRIPT } from "@/lib/prefs";
import { robots, SITE_NAME } from "@/lib/seo";
import "./globals.css";

export const metadata: Metadata = {
  title: "GutHub｜大腸直腸外科實證更新",
  description:
    "整理大腸直腸外科的文獻、研究結果與資料來源，供醫療專業人員閱讀與參考。",
  robots: robots(),
  alternates: {
    types: {
      "application/rss+xml": [
        { url: "/rss.xml", title: `${SITE_NAME}｜全部更新（RSS）` },
        { url: "/feed/news.xml", title: `${SITE_NAME}｜最新消息（RSS）` },
      ],
      "application/atom+xml": [
        { url: "/atom.xml", title: `${SITE_NAME}｜全部更新（Atom）` },
      ],
      "application/feed+json": [
        { url: "/feed.json", title: `${SITE_NAME}｜全部更新（JSON Feed）` },
      ],
    },
  },
  icons: { icon: "/favicon.svg" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0E2270",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // PREFS_SCRIPT sets data-theme / data-font-size on <html> before hydration.
    <html lang="zh-Hant-TW" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: PREFS_SCRIPT }} />
      </head>
      <body>
        <a className="skip-link" href="#main">
          跳到主要內容
        </a>
        <SiteHeader />
        <main id="main">{children}</main>
        <footer className="site-footer">
          <div className="container site-footer__grid">
            <div>
              <p>
                本站供醫療專業人員教育與臨床參考，不構成醫療建議。新聞稿由 AI
                撰寫，部分文獻由 AI 整理；標示「尚未經人工審核」或「AI
                未審」的內容可能有誤，臨床決策請以原始文獻與現行指引為準。
              </p>
              <nav aria-label="頁尾導覽">
                <Link href="/about/">關於本站與 AI 使用說明</Link>
                <Link href="/subscribe/">推播與 RSS 訂閱</Link>
                <Link href="/updates/">全部文獻</Link>
              </nav>
            </div>
            <DisplaySettings />
          </div>
        </footer>
        <TabBar />
        <OfflineReading />
      </body>
    </html>
  );
}
