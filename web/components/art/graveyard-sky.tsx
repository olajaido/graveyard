/**
 * The ground behind the results header: two hills, full width, anchored to the bottom edge. Ported from
 * Graveyard.dc.html. Decorative. The moon and the stars are `SkyObjects`, in their own layer, so they stay out of the
 * text column.
 */
export function GraveyardSky({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 1440 300"
      preserveAspectRatio="xMidYMax slice"
      className={className}
    >
      <path
        d="M0 250 C260 214 520 236 760 240 C1000 244 1200 210 1440 222 V300 H0 Z"
        fill="#171B23"
      />
      <path
        d="M0 280 C360 262 720 276 1080 268 C1260 264 1360 270 1440 272 V300 H0 Z"
        fill="#0D0F13"
      />
    </svg>
  );
}
/**
 * The moon and the stars of the results header (from Graveyard.dc.html). The box is a fixed 500 by 300 and sits at the
 * top right, never scaled with the height of the header. The parent places it to the right of the text column.
 */
export function SkyObjects({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 500 300"
      preserveAspectRatio="xMaxYMin meet"
      className={className}
    >
      <g fill="#E8E1CF">
        <circle cx="40" cy="50" r="1.3" />
        <circle cx="130" cy="30" r="1" />
        <circle cx="210" cy="90" r="1.2" />
        <circle cx="270" cy="40" r="1" />
        <circle cx="170" cy="150" r="1.3" />
        <circle cx="460" cy="190" r="1.1" />
        <circle cx="320" cy="170" r="1" />
      </g>
      <circle cx="380" cy="125" r="110" fill="#E8E1CF" opacity="0.04" />
      <circle cx="380" cy="125" r="44" fill="#E8E1CF" />
      <circle cx="366" cy="115" r="7" fill="#D7CFBB" />
      <circle cx="392" cy="139" r="9" fill="#D7CFBB" />
    </svg>
  );
}
