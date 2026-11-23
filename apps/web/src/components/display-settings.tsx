"use client";

// Theme toggle and text-size buttons, as base.html.j2 lays them out in the header and footer.
import { useSyncExternalStore } from "react";
import { Icon } from "@/components/reading";
import {
  applyFontSize,
  FONT_SIZES,
  nextTheme,
  savePref,
  type FontSize,
} from "@/lib/prefs";

function toggleTheme() {
  const root = document.documentElement;
  root.dataset.theme = nextTheme(
    root.dataset.theme,
    matchMedia("(prefers-color-scheme: dark)").matches,
  );
  savePref("theme", root.dataset.theme);
}

// The text size lives on <html data-font-size> (set before paint by PREFS_SCRIPT); every button group reads it there.
function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributeFilter: ["data-font-size"],
  });
  return () => observer.disconnect();
}
const currentSize = () =>
  (document.documentElement.dataset.fontSize ?? "md") as FontSize;

export function ThemeToggle({ labelled = false }: { labelled?: boolean }) {
  return labelled ? (
    <button className="btn btn--secondary" type="button" onClick={toggleTheme}>
      <Icon name="theme" />
      深色模式
    </button>
  ) : (
    <button
      className="btn btn--quiet btn--icon"
      type="button"
      aria-label="切換深色模式"
      title="切換深色模式"
      onClick={toggleTheme}
    >
      <Icon name="theme" />
    </button>
  );
}

export function DisplaySettings({
  labelId = "text-size-label",
}: {
  labelId?: string;
} = {}) {
  const size = useSyncExternalStore(subscribe, currentSize, () => "md");
  return (
    <div className="display-settings">
      <span id={labelId}>文字大小</span>
      <span className="segmented" role="group" aria-labelledby={labelId}>
        {FONT_SIZES.map(([option, label]) => (
          <button
            type="button"
            key={option}
            data-font-size-option={option}
            aria-pressed={size === option}
            aria-label={label}
            onClick={() => {
              applyFontSize(document.documentElement, option);
              savePref("fontSize", option);
            }}
          >
            A
          </button>
        ))}
      </span>
      <ThemeToggle labelled />
    </div>
  );
}
