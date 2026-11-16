"use client";

// Header navigation and the mobile tab bar, marking the current area like base.html.j2 does.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "@/components/reading";
import { areaOf, NAV, TABS } from "@/lib/site";

export function SiteNav() {
  const area = areaOf(usePathname());
  return (
    <nav className="site-nav" aria-label="主要導覽">
      {NAV.map(([label, href, key]) => (
        <Link
          href={href}
          key={href}
          aria-current={area === key ? "page" : undefined}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}

export function TabBar() {
  const area = areaOf(usePathname());
  return (
    <nav className="tabbar" aria-label="分頁導覽">
      {TABS.map(([label, href, key, glyph]) => (
        <Link
          href={href}
          key={href}
          aria-current={area === key ? "page" : undefined}
        >
          <Icon name={glyph as IconName} />
          {label}
        </Link>
      ))}
    </nav>
  );
}
