// Weekly activity for the maintainer (G10 #121). The API sends counts only; this turns them into table rows.
import type { components } from "./api.generated";

export type Week = components["schemas"]["WeeklyActivity"]["weeks"][number];

/** Oldest first, as the API sends them; `bar` is the active readers as a share of the busiest week. */
export function activityRows(weeks: Week[]) {
  const most = Math.max(0, ...weeks.map((w) => w.activeReaders));
  return weeks.map((w, index) => {
    const [, month, day] = w.week.split("-").map(Number);
    const current = index === weeks.length - 1;
    return {
      ...w,
      label: `${month}/${day} 起${current ? "（本週）" : ""}`,
      bar: most ? Math.round((w.activeReaders / most) * 100) : 0,
      current,
    };
  });
}

export function activitySummary(weeks: Week[]): string {
  const [last, now] = weeks.slice(-2);
  return `本週到目前有 ${now.activeReaders} 位讀者留言、按讚或檢舉；上週 ${last.activeReaders} 位。`;
}
