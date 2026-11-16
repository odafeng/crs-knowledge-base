import Link from "next/link";
import { Icon } from "@/components/reading";
import { SiteNav } from "@/components/site-nav";

export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="container site-header__inner">
        <Link className="brand" href="/" aria-label="GutHub 首頁">
          <svg className="brand__mark" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="#1B3BC4" />
            <path
              d="M7 9h3v9h7v5h8"
              fill="none"
              stroke="#fff"
              strokeOpacity=".45"
              strokeWidth="2.5"
            />
            <path
              d="M7 9h6v6h6v5h5"
              fill="none"
              stroke="#fff"
              strokeWidth="2.5"
            />
            <circle cx="25" cy="20" r="2.75" fill="#FF8FB1" />
          </svg>
          <span className="brand__text">
            <span className="brand__name">GutHub</span>
            <span className="brand__desc">大腸直腸外科實證更新</span>
          </span>
        </Link>
        <SiteNav />
        <Link
          className="btn btn--quiet btn--icon"
          href="/updates/#q"
          aria-label="搜尋消息與文獻"
        >
          <Icon name="search" />
        </Link>
      </div>
    </header>
  );
}
