export default function Home() {
  return (
    <>
      <section className="lead on-field" aria-labelledby="site-title">
        <div className="container reading-intro">
          <h1 id="site-title">
            大腸直腸外科
            <br />
            實證與討論
          </h1>
          <p className="lead__dek">
            從臨床試驗、治療指引到手術實證，整理研究結果，也保留資料來源與判讀限制。
          </p>
          <a
            className="btn btn--primary"
            href="https://odafeng.github.io/crs-knowledge-base/updates/"
          >
            閱讀文獻
          </a>
        </div>
      </section>
      <section
        className="container reading-intro"
        aria-labelledby="evidence-title"
      >
        <h2 id="evidence-title">從摘要回到原始證據</h2>
        <p>
          每個文獻條目保留來源、關鍵結果與審核狀態，讓閱讀與討論都能回到可查核的依據。
        </p>
      </section>
    </>
  );
}
