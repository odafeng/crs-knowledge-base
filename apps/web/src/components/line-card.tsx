// Full LINE Official Account card for /subscribe/#line with scannable QR code and one-tap friend link.
import { Icon } from "@/components/reading";
import { LINE_OA } from "@/lib/line-oa";
import styles from "./line-card.module.css";

export function LineCard() {
  return (
    <section className={styles.lineCard} id="line" aria-labelledby="line-title">
      <div className={styles.body}>
        <p className={styles.kicker}>LINE 官方帳號</p>
        <h2 id="line-title">早上 7 點收一則白話重點</h2>
        <p className={styles.text}>
          有新文獻或消息才推送，每天最多一則，沒有更新就不打擾。不用註冊、也不用留
          Email。
        </p>
        <p className={styles.id}>
          官方帳號 ID：<code>{LINE_OA.id}</code>
        </p>
        <div className={styles.actions}>
          <a
            className="btn btn--primary"
            href={LINE_OA.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            <Icon name="chat" />
            加入 GutHub LINE 好友
          </a>
        </div>
      </div>
      <figure className={styles.qr}>
        {/* Local 1.5 KB vector SVG QR code; static img keeps dark-mode quiet zone crisp without optimization overhead. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={LINE_OA.qrSrc}
          alt={`掃描 QR code 加入 GutHub LINE 官方帳號（${LINE_OA.id}）`}
          width={156}
          height={156}
          loading="lazy"
          decoding="async"
        />
        <figcaption>手機掃描加入好友</figcaption>
      </figure>
    </section>
  );
}
