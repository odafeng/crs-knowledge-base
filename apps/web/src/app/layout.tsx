import type { Metadata, Viewport } from "next";
import { SiteHeader } from "@/components/site-header";
import "./globals.css";

export const metadata: Metadata = {
  title: "GutHub｜大腸直腸外科實證更新",
  description:
    "整理大腸直腸外科的文獻、研究結果與資料來源，供醫療專業人員閱讀與參考。",
  robots: { index: false, follow: false },
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
    <html lang="zh-Hant-TW">
      <body>
        <a className="skip-link" href="#main">
          跳到主要內容
        </a>
        <SiteHeader />
        <main id="main">{children}</main>
        <footer className="site-footer">
          <div className="container">
            <p>
              本站供醫療專業人員教育與臨床參考，不構成醫療建議。臨床判斷請以原始文獻與現行指引為準。
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
