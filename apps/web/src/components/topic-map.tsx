// The home page's topics as a small chart (J8): each topic a tile with its count and a bar for how much evidence it
// has next to the busiest topic in its group, so the reader sees where the evidence is before opening one.
import type { CSSProperties } from "react";
import Link from "next/link";

type Row = { key: string; href: string; name: string; count: number };

export function TopicMap({
  label,
  unit,
  rows,
}: {
  label: string;
  unit: string;
  rows: readonly Row[];
}) {
  if (rows.length === 0) return null;
  const most = Math.max(1, ...rows.map((row) => row.count));
  return (
    <div className="topic-map">
      <h3 className="topic-map__label">{label}</h3>
      <ul className="topic-map__grid">
        {rows.map((row) => (
          <li key={row.key}>
            <Link
              className="topic-tile"
              href={row.href}
              style={{ "--share": row.count / most } as CSSProperties}
            >
              <span className="topic-tile__name">{row.name}</span>
              <span className="topic-tile__count">
                <span className="num">{row.count}</span> {unit}
              </span>
              <span className="topic-tile__bar" aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
