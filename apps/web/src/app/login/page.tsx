import type { Metadata } from "next";
import { LoginForm } from "@/components/sign-in";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `登入｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default function LoginPage() {
  return (
    <div className="container auth-page">
      <div className="auth-shell">
        <header className="auth-shell__head">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            className="auth-shell__mark"
            src="/icons/mark-96.png"
            alt=""
            width={40}
            height={40}
          />
          <h1>登入 GutHub</h1>
          <p className="auth-shell__lead">
            登入後可以在文獻頁留言，或驗證身分進入醫師論壇。閱讀文獻不需要登入。
          </p>
        </header>
        <LoginForm />
      </div>
    </div>
  );
}
