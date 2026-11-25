import { useSvgId } from './use-svg-id';

/** The picket fence above the footer. Ported from Main.dc.html. Decorative. */
export function FenceStrip({ className }: { className?: string }) {
  const picket = useSvgId('gyPicket2');
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 1440 60"
      preserveAspectRatio="none"
      className={className}
    >
      <defs>
        <pattern id={picket} width="20" height="56" patternUnits="userSpaceOnUse">
          <path d="M10 2 L14 11 L10 9 L6 11 Z" fill="#20252D" />
          <rect x="8.6" y="9" width="2.8" height="47" fill="#20252D" />
        </pattern>
      </defs>
      <rect x="0" y="4" width="1440" height="56" fill={`url(#${picket})`} />
      <rect x="0" y="22" width="1440" height="3" fill="#20252D" />
      <rect x="0" y="44" width="1440" height="3" fill="#20252D" />
    </svg>
  );
}
