/** The gravestone mark of the Graveyard logo. Decorative. Draws in the current text colour. */
export function BrandMark({
  width = 28,
  height = 32,
  strokeWidth = 1.6,
  className,
}: {
  width?: number;
  height?: number;
  strokeWidth?: number;
  className?: string;
}) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 28 32"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <path d="M3 31V13a11 11 0 0 1 22 0v18" />
      <path d="M1 31h26" />
      <path d="M14 8v12M9.5 12.5h9" />
    </svg>
  );
}
