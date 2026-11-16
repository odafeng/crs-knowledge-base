import Link from "next/link";

export default function NotFound() {
  return (
    <div className="container page reading-intro">
      <h1>找不到這一頁</h1>
      <p>這個網址可能打錯了，或內容已經撤下。</p>
      <p>
        <Link className="btn btn--primary" href="/">
          回到首頁
        </Link>
      </p>
    </div>
  );
}
