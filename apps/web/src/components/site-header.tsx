import Link from "next/link";
import { AccountLink } from "@/components/account";
import { ThemeToggle } from "@/components/display-settings";
import { Icon } from "@/components/reading";
import { SiteNav } from "@/components/site-nav";

export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="container site-header__inner">
        <Link className="brand" href="/">
          {/* A 4 KB static icon from tools/icons.js; next/image would only add an optimisation round trip. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            className="brand__mark"
            src="/icons/mark-96.png"
            alt=""
            width={32}
            height={32}
          />
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
        <ThemeToggle />
        <AccountLink />
      </div>
    </header>
  );
}
