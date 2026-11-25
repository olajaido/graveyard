import { useSvgId } from './use-svg-id';

/**
 * Hills, picket fence and ground behind one plot. Ported from Graveyard.dc.html: the shapes and coordinates are the
 * mockup's. The plot places the svg so that y = 200 (the foot of the fence) is the top edge of the stones panel.
 * Colours are from the palette: the hill is `hairline` (a step lighter than `night`), the pickets are the dark
 * silhouette with a faint moonlit edge (`stone-line`) on the side facing the moon, and the rails have the same edge
 * along their top. Decorative.
 */
export function PlotBackdrop({ className }: { className?: string }) {
  const picket = useSvgId('gyPk');
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 1200 260"
      preserveAspectRatio="none"
      className={className}
    >
      <path
        d="M0 150 C200 120 420 136 640 140 C860 144 1000 116 1200 126 V260 H0 Z"
        fill="#1E232B"
      />
      <defs>
        <pattern id={picket} width="18" height="50" patternUnits="userSpaceOnUse">
          <path d="M9 2 L12.5 10 L9 8 L5.5 10 Z" fill="#0B0D11" />
          <rect x="7.8" y="8" width="2.4" height="42" fill="#0B0D11" />
          <rect x="10.2" y="9" width="0.8" height="41" fill="#3E444E" />
          <path d="M12.5 10 L9 2" stroke="#3E444E" strokeWidth="0.8" fill="none" />
        </pattern>
      </defs>
      <rect x="0" y="150" width="1200" height="50" fill={`url(#${picket})`} />
      <rect x="0" y="165" width="1200" height="3" fill="#0B0D11" />
      <rect x="0" y="164.2" width="1200" height="0.8" fill="#3E444E" />
      <rect x="0" y="188" width="1200" height="3" fill="#0B0D11" />
      <rect x="0" y="187.2" width="1200" height="0.8" fill="#3E444E" />
      <path
        d="M0 210 C300 196 600 206 900 200 C1040 198 1120 202 1200 204 V260 H0 Z"
        fill="#0F1217"
      />
    </svg>
  );
}
