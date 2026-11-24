import { authorInitials, avatarTone } from "@/lib/forum";
import styles from "./avatar.module.css";

const SIZE_CLASS = {
  xs: styles.xs,
  sm: styles.sm,
  md: styles.md,
  lg: styles.lg,
} as const;

const TONE_CLASS = {
  0: styles.tone0,
  1: styles.tone1,
  2: styles.tone2,
  3: styles.tone3,
  4: styles.tone4,
} as const;

export function Avatar({
  name,
  anonymous = false,
  ai = false,
  size = "md",
}: {
  name?: string | null;
  anonymous?: boolean;
  ai?: boolean;
  size?: "xs" | "sm" | "md" | "lg";
}) {
  const initials = authorInitials(name, { anonymous, ai });
  const toneClass = ai
    ? styles.ai
    : anonymous
      ? styles.anon
      : TONE_CLASS[avatarTone(name ?? "member")];
  return (
    <span
      className={`${styles.avatar} ${SIZE_CLASS[size]} ${toneClass}`}
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}
