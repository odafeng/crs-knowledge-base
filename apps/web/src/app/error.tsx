"use client";

// Shown when the content API cannot be reached; pages already generated keep being served by ISR.
export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="container page reading-intro" role="alert">
      <h1>暫時無法載入內容</h1>
      <p>資料服務目前沒有回應，請稍後再試。</p>
      <p>
        <button className="btn btn--primary" type="button" onClick={reset}>
          重新載入
        </button>
      </p>
    </div>
  );
}
