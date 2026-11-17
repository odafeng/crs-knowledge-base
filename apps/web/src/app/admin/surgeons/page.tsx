import type { Metadata } from "next";
import { SurgeonReview } from "@/components/surgeon-review";
import { SITE_NAME } from "@/lib/seo";

export const metadata: Metadata = {
  title: `會員審核｜${SITE_NAME}`,
  robots: { index: false, follow: false },
};

export default function SurgeonReviewPage() {
  return (
    <div className="container page">
      <header className="page-head">
        <h1>大腸直腸外科會員審核</h1>
        <p className="page-head__lead">
          專科醫師請對照大腸直腸外科醫學會的專科醫師名單；受訓中的住院醫師與
          fellow
          請對照衛福部醫事人員查詢與執業院所。核准或退回後，申請資料會立即刪除。
        </p>
      </header>
      <div className="page__narrow">
        <SurgeonReview />
      </div>
    </div>
  );
}
