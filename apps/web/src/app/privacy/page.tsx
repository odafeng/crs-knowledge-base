import type { Metadata } from "next";
import Link from "next/link";
import { Breadcrumb, JsonLd } from "@/components/reading";
import { pageJsonLd, pageMetadata } from "@/lib/seo";
import { HOME } from "@/lib/site";

// Every statement here must match what the code does (C6 #110); update this page in the same change as the code.
const UPDATED = "2026-11-17";
const CONTACT = "privacy@guthub.tw";
const TITLE = "隱私權政策";
const DESCRIPTION =
  "GutHub 蒐集哪些資料、為什麼蒐集、存在哪裡、保存多久，以及你可以怎麼查詢或刪除。";

export const metadata: Metadata = pageMetadata(TITLE, DESCRIPTION, "/privacy/");

export default function PrivacyPage() {
  const crumbs = [...HOME, [TITLE, "/privacy/"] as const];
  return (
    <div className="container page">
      <JsonLd data={pageJsonLd(TITLE, DESCRIPTION, "/privacy/", crumbs)} />
      <Breadcrumb crumbs={crumbs} />
      <header className="page-head">
        <h1>{TITLE}</h1>
        <p className="page-head__lead">最後更新：{UPDATED}</p>
      </header>
      <div className="page__narrow prose">
        <p>
          GutHub
          是給大腸直腸外科醫師的實證更新站。這一頁說明我們蒐集哪些資料、用途、存放位置與保存期限。
          我們不投放廣告，不出售也不出租任何人的資料。
        </p>

        <h2>不登入就能閱讀</h2>
        <p>
          閱讀文獻、消息與主題頁都不需要帳號。網站沒有安裝廣告、追蹤 cookie
          或第三方分析服務。主機與資料庫服務商（見下方「資料存放在哪裡」）會依各自的政策保留連線紀錄，
          例如 IP 位址與瀏覽器版本，用於維運與防止濫用。
        </p>

        <h2>存在你瀏覽器裡的資料</h2>
        <ul>
          <li>深色模式與字級設定，只用來顯示頁面。</li>
          <li>登入後的登入狀態（登入 token），以及登入完成後要回到哪一頁。</li>
          <li>
            離線閱讀用的快取：只存公開的頁面與搜尋索引，不存登入資料、留言作者或管理頁面。
          </li>
        </ul>
        <p>
          這些資料只在你的裝置上。清除瀏覽器的網站資料或登出就會移除登入狀態。
        </p>

        <h2>登入與帳號</h2>
        <p>
          留言、按讚與檢舉需要登入。登入由 Supabase Auth 處理，可以選擇 Email
          一次性連結或 Google 帳號，不使用密碼。
        </p>
        <ul>
          <li>
            Email 登入：我們保存你的 Email，用來寄登入連結（透過寄信服務 Resend
            寄出）。
          </li>
          <li>
            Google 登入：我們向 Google 取得你的 Email 與 Google
            帳號識別碼。Supabase 也會保存 Google
            提供的基本資料（例如姓名、頭像網址），本站不會公開或使用這些資料。
          </li>
          <li>
            顯示名稱：第一次登入時由你自己填寫，不會自動帶入 Google 姓名或
            Email。你可以在
            <Link href="/account/">帳號設定</Link>隨時修改。
          </li>
        </ul>
        <p>Email 與 Google 資料不會公開，也不會顯示在任何頁面上。</p>

        <h2>留言、匿名、按讚與檢舉</h2>
        <ul>
          <li>
            公開的留言內容所有人都看得到。署名留言會顯示發文當時的顯示名稱；之後改名，舊留言仍顯示當時的名稱。
          </li>
          <li>
            匿名留言不會對其他讀者顯示你的名稱。平台仍保留這則留言是誰寫的，只有你本人和維護者看得到：
            你需要它來修改或刪除自己的留言；維護者只在處理檢舉或濫用時查看，而且每次查看都會連同原因記錄。
          </li>
          <li>
            帳號的第一則留言會先由維護者審核，之後的留言直接公開，被檢舉時再處理。
          </li>
          <li>
            按讚：公開的只有讚數。誰按了讚不會公開，只有你自己看得到你按過哪些。
          </li>
          <li>
            檢舉：檢舉人與理由只有維護者看得到，不會讓被檢舉的人知道是誰檢舉。
          </li>
        </ul>
        <p>讀者留言不會成為文獻整理的內容或來源，也不會送進 AI 模型。</p>

        <h2>推播通知</h2>
        <p>
          開啟推播時，我們保存瀏覽器提供的推播位址與加密金鑰，用來傳送新消息通知。這些資料不會連到你的帳號。
          關閉推播就會刪除。
        </p>

        <h2>資料存放在哪裡</h2>
        <ul>
          <li>
            Supabase（資料庫與登入，東京區域）：帳號、顯示名稱、留言、按讚、檢舉與審核紀錄。
          </li>
          <li>
            Google Cloud（東京區域）：處理留言與帳號請求的 API
            程式，以及文獻整理排程。
          </li>
          <li>Vercel：網站頁面的主機。</li>
          <li>Resend：寄送 Email 登入連結。</li>
          <li>Google：使用 Google 登入時的身分驗證。</li>
        </ul>

        <h2>AI 的使用</h2>
        <p>
          消息稿由 AI 撰寫，部分文獻由 AI 依摘要整理，詳見
          <Link href="/about/">關於本站</Link>。
          這些流程只處理公開的文獻資料，不使用讀者的帳號、留言或瀏覽資料。
        </p>

        <h2>保存期限與刪除</h2>
        <ul>
          <li>
            你可以隨時刪除自己的留言，刪除後立即對所有人隱藏。平台會保留這則留言的作者對應
            90 天，供處理檢舉與濫用，之後清除。
          </li>
          <li>
            刪除帳號請來信（見下方）。我們會刪除你的登入資料（Email、Google
            帳號識別碼）、顯示名稱與作者對應， 你的留言會一併對所有人隱藏。
          </li>
          <li>
            審核與查閱身分的紀錄會保留，讓每次審核都可以追溯；紀錄中不含 Email。
          </li>
        </ul>

        <h2>你的權利與聯絡方式</h2>
        <p>
          依個人資料保護法，你可以查詢、閱覽、更正、停止使用或刪除你的個人資料。顯示名稱可以自己在帳號設定修改；
          其他請求，例如刪除帳號，請寄信至{" "}
          <a href={`mailto:${CONTACT}`}>{CONTACT}</a>，我們會在 14 天內回覆。
        </p>

        <h2>本政策的更新</h2>
        <p>
          網站處理資料的方式改變時，我們會同步更新這一頁，並修改上方的「最後更新」日期。
        </p>
      </div>
    </div>
  );
}
