import type { Metadata } from "next";
import { LoginForm } from "@/components/sign-in";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `登入｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default function LoginPage() {
  return (
    <div className="container page">
      <header className="page-head">
        <h1>登入</h1>
        <p className="page-head__lead">
          登入後可以在文獻頁留言，署名或匿名都可以。閱讀不需要登入。
        </p>
      </header>
      <div className="page__narrow">
        <LoginForm />
      </div>
    </div>
  );
}
