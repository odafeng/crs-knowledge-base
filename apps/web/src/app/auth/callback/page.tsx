import type { Metadata } from "next";
import { AuthCallback } from "@/components/sign-in";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `登入｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default function AuthCallbackPage() {
  return (
    <div className="container page">
      <header className="page-head">
        <h1>登入</h1>
      </header>
      <div className="page__narrow">
        <AuthCallback />
      </div>
    </div>
  );
}
