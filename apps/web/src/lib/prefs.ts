// Reader preferences (theme, text size), remembered on this device only, as prefs.js does on the current site.
// Until the reader picks a theme, CSS follows the system setting by itself.

export type Theme = "light" | "dark";
export type FontSize = "md" | "lg" | "xl";
export const FONT_SIZES: ReadonlyArray<readonly [FontSize, string]> = [
  ["md", "標準字級"],
  ["lg", "大字級"],
  ["xl", "特大字級"],
];

/** Runs in <head> before first paint, so a saved preference never flashes the default (Next.js "Preventing Flash"). */
export const PREFS_SCRIPT =
  "(function(){var d=document.documentElement,t,f;try{t=localStorage.getItem('theme');f=localStorage.getItem('fontSize');}catch(e){}if(t)d.dataset.theme=t;if(f&&f!=='md')d.dataset.fontSize=f;})();";

export function savePref(key: "theme" | "fontSize", value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Private mode or storage disabled: the choice lasts for this page only.
  }
}

/** The theme a toggle switches to: the opposite of the explicit choice, or of the system setting when none. */
export function nextTheme(
  current: string | undefined,
  systemDark: boolean,
): Theme {
  const shown = current || (systemDark ? "dark" : "light");
  return shown === "dark" ? "light" : "dark";
}

export function applyFontSize(root: HTMLElement, size: FontSize): void {
  if (size === "md") delete root.dataset.fontSize;
  else root.dataset.fontSize = size;
}
