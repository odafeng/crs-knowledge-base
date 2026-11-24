// A story's numbers, drawn to scale (templates/_figure.html.j2). Values are printed as text beside every mark.
import type { CSSProperties } from "react";
import { barWidth, fmt, intervalScale } from "@/lib/figures";
import type { Figure, News } from "@/lib/site";
import styles from "./news-figure.module.css";

const vars = (values: Record<string, string>) => values as CSSProperties;

function Block({ figure }: { figure: Figure }) {
  switch (figure.kind) {
    case "numbers":
      return (
        <dl className={styles.stats} data-figure-kind="numbers">
          {figure.stats.map((stat) => (
            <div className={styles.stat} key={stat.label}>
              <dt className={styles.statLabel}>{stat.label}</dt>
              <dd className={`${styles.statValue} num`}>
                {stat.value}
                <span className={styles.statUnit}>{stat.unit}</span>
              </dd>
            </div>
          ))}
        </dl>
      );
    case "compare":
      return (
        <>
          <ul className={styles.legend} aria-hidden="true">
            <li>{figure.armA}</li>
            <li>{figure.armB}</li>
          </ul>
          {figure.rows.map((row) => (
            <table
              className={styles.compare}
              data-figure-kind="compare"
              key={row.label}
            >
              <caption>
                {row.label} <span>（{row.unit}）</span>
              </caption>
              <tbody>
                {(
                  [
                    [figure.armA, row.a, `${styles.bar} ${styles.barA}`],
                    [figure.armB, row.b, styles.bar],
                  ] as const
                ).map(([arm, value, className]) => (
                  <tr key={arm}>
                    <th scope="row" className="visually-hidden">
                      {arm}
                    </th>
                    <td>
                      <span
                        className={className}
                        style={vars({
                          "--w": `${barWidth(figure.rows, row, value)}%`,
                        })}
                      >
                        <span className={`${styles.barValue} num`}>
                          {fmt(value)}
                        </span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
        </>
      );
    case "meters":
      return (
        <ul className={styles.meters} data-figure-kind="meters">
          {figure.rows.map((meter) => (
            <li className={styles.meter} key={meter.label}>
              <span className={styles.meterLabel}>{meter.label}</span>
              <span className={`${styles.meterValue} num`}>
                {fmt(meter.percent)}%
              </span>
              <span className={styles.meterTrack} aria-hidden="true">
                <span
                  className={styles.meterFill}
                  style={vars({ "--w": `${meter.percent}%` })}
                />
              </span>
              {meter.detail && (
                <span className={styles.meterDetail}>{meter.detail}</span>
              )}
            </li>
          ))}
        </ul>
      );
    case "interval": {
      const { x, ticks } = intervalScale(figure);
      return (
        <>
          <div className={styles.intervalHead}>
            <span className={styles.intervalLabel}>{figure.label}</span>
            <span className={styles.intervalValue}>
              <span className="num">{fmt(figure.point)}</span>（95% CI{" "}
              {fmt(figure.low)}–{fmt(figure.high)}）
            </span>
          </div>
          <div className={styles.intervalScale} aria-hidden="true">
            <div className={styles.intervalPlot}>
              <span
                className={styles.intervalRef}
                style={vars({ "--x": `${x(1)}%` })}
              />
              <span
                className={styles.intervalWhisker}
                style={vars({
                  "--from": `${x(figure.low)}%`,
                  "--to": `${x(figure.high)}%`,
                })}
              />
              <span
                className={styles.intervalPoint}
                data-figure-part="interval-point"
                style={vars({ "--x": `${x(figure.point)}%` })}
              />
            </div>
            <div className={styles.intervalTicks}>
              {ticks.map(([label, position]) => (
                <span key={label} style={vars({ "--x": `${position}%` })}>
                  {label}
                </span>
              ))}
            </div>
          </div>
          {figure.note && <p className={styles.intervalNote}>{figure.note}</p>}
        </>
      );
    }
  }
}

export function DataFigure({
  figures,
  title = "關鍵數字",
  caption,
  spaced = false,
  className,
}: {
  figures: readonly Figure[];
  title?: string;
  caption?: string;
  spaced?: boolean;
  className?: string;
}) {
  if (figures.length === 0) return null;
  const rootClass = [
    styles.figure,
    spaced ? styles.paperFigure : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <figure className={rootClass} data-figure="">
      <p className={styles.title}>{title}</p>
      {figures.map((figure, index) => (
        <div className={styles.block} key={index}>
          <Block figure={figure} />
        </div>
      ))}
      {caption && <figcaption className={styles.caption}>{caption}</figcaption>}
    </figure>
  );
}

export function NewsFigure({
  item,
  title = "關鍵數字",
}: {
  item: News;
  title?: string;
}) {
  return (
    <DataFigure
      figures={item.figures}
      title={title}
      caption={item.figureNote}
    />
  );
}
