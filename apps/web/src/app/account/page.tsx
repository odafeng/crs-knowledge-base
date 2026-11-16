import type { Metadata } from "next";
import { AccountSettings } from "@/components/sign-in";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `帳號設定｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default function AccountPage() {
  return (
    <div className="container page">
      <header className="page-head">
        <h1>帳號設定</h1>
      </header>
      <div className="page__narrow">
        <AccountSettings />
      </div>
    </div>
  );
}
