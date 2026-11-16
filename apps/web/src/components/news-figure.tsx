// A story's numbers, drawn to scale (templates/_figure.html.j2). Values are printed as text beside every mark.
import type { CSSProperties } from "react";
import { barWidth, fmt, intervalScale } from "@/lib/figures";
import type { Figure, News } from "@/lib/site";

const vars = (values: Record<string, string>) => values as CSSProperties;

function Block({ figure }: { figure: Figure }) {
  switch (figure.kind) {
    case "numbers":
      return (
        <dl className="stats">
          {figure.stats.map((stat) => (
            <div className="stat" key={stat.label}>
              <dt className="stat__label">{stat.label}</dt>
              <dd className="stat__value num">
                {stat.value}
                <span className="stat__unit">{stat.unit}</span>
              </dd>
            </div>
          ))}
        </dl>
      );
    case "compare":
      return (
        <>
          <ul className="legend" aria-hidden="true">
            <li>{figure.armA}</li>
            <li>{figure.armB}</li>
          </ul>
          {figure.rows.map((row) => (
            <table className="compare" key={row.label}>
              <caption>
                {row.label} <span>（{row.unit}）</span>
              </caption>
              <tbody>
                {(
                  [
                    [figure.armA, row.a, "bar bar--a"],
                    [figure.armB, row.b, "bar"],
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
                        <span className="bar__value num">{fmt(value)}</span>
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
        <ul className="meters">
          {figure.rows.map((meter) => (
            <li className="meter" key={meter.label}>
              <span className="meter__label">{meter.label}</span>
              <span className="meter__value num">{fmt(meter.percent)}%</span>
              <span className="meter__track" aria-hidden="true">
                <span
                  className="meter__fill"
                  style={vars({ "--w": `${meter.percent}%` })}
                />
              </span>
              {meter.detail && (
                <span className="meter__detail">{meter.detail}</span>
              )}
            </li>
          ))}
        </ul>
      );
    case "interval": {
      const { x, ticks } = intervalScale(figure);
      return (
        <>
          <div className="interval__head">
            <span className="interval__label">{figure.label}</span>
            <span className="interval__value">
              <span className="num">{fmt(figure.point)}</span>（95% CI{" "}
              {fmt(figure.low)}–{fmt(figure.high)}）
            </span>
          </div>
          <div className="interval__scale" aria-hidden="true">
            <div className="interval__plot">
              <span
                className="interval__ref"
                style={vars({ "--x": `${x(1)}%` })}
              />
              <span
                className="interval__whisker"
                style={vars({
                  "--from": `${x(figure.low)}%`,
                  "--to": `${x(figure.high)}%`,
                })}
              />
              <span
                className="interval__point"
                style={vars({ "--x": `${x(figure.point)}%` })}
              />
            </div>
            <div className="interval__ticks">
              {ticks.map(([label, position]) => (
                <span key={label} style={vars({ "--x": `${position}%` })}>
                  {label}
                </span>
              ))}
            </div>
          </div>
          {figure.note && <p className="interval__note">{figure.note}</p>}
        </>
      );
    }
  }
}

export function NewsFigure({
  item,
  title = "關鍵數字",
}: {
  item: News;
  title?: string;
}) {
  return (
    <figure className="figure">
      <p className="figure__title">{title}</p>
      {item.figures.map((figure, index) => (
        <div className="figure__block" key={index}>
          <Block figure={figure} />
        </div>
      ))}
      {item.figureNote && (
        <figcaption className="figure__caption">{item.figureNote}</figcaption>
      )}
    </figure>
  );
}
