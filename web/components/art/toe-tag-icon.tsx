/** The ring and string of a toe tag (22 by 22). Ported from Exhumation.dc.html. `color` is the state ink. Decorative. */
export function ToeTagIcon({ color, className }: { color: string; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="22"
      height="22"
      viewBox="0 0 22 22"
      className={className}
    >
      <circle cx="11" cy="11" r="6" fill="none" stroke={color} strokeWidth="2" />
      <path d="M0 11 H5" stroke="#8C8371" strokeWidth="1.4" />
    </svg>
  );
}
