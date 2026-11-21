import { authorInitials, avatarTone } from "@/lib/forum";

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
    ? "avatar--ai"
    : anonymous
      ? "avatar--anon"
      : `avatar--tone-${avatarTone(name ?? "member")}`;
  return (
    <span className={`avatar avatar--${size} ${toneClass}`} aria-hidden="true">
      {initials}
    </span>
  );
}
