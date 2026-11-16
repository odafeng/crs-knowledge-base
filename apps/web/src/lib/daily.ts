// The home page's "today's one thing" (G4 #115), from the API's daily pick (G2 #113).
import type { components } from "./api.generated";

export type DailyPick = components["schemas"]["DailyPick"];

/** Today's pick is "today's"; a fallback from an earlier day says which day, so nothing old looks new. */
export function dailyLabel(pickDate: string, today: string): string {
  if (pickDate === today) return "今天的一件事";
  const [, month, day] = pickDate.split("-").map(Number);
  return `最近的一件事・${month} 月 ${day} 日`;
}
