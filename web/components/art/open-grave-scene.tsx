/**
 * The open grave of the Exhumation page, ported from Exhumation.dc.html with the shapes unchanged. The mockup's
 * `role="img"` label and its "68% deep" text are dropped: the scene is decorative and the real numbers are in the
 * page text.
 *
 * `depth` (0 to 1) is the dig depth. A backfill of the ground colour covers the pit from the bottom and uncovers it
 * as `depth` grows, so the coffin shows when the dig is nearly done. It is added on top of the original shapes.
 */
export const PIT = { x: 610, top: 262, width: 230, height: 140 } as const;

export function OpenGraveScene({ depth = 0, className }: { depth?: number; className?: string }) {
  const d = Math.min(1, Math.max(0, Number.isFinite(depth) ? depth : 0));
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 1440 420"
      preserveAspectRatio="xMidYMax slice"
      className={className}
    >
      <g fill="#E8E1CF">
        <circle cx="140" cy="60" r="1.2" />
        <circle cx="420" cy="40" r="1" />
        <circle cx="1000" cy="50" r="1.3" />
        <circle cx="1180" cy="120" r="1" />
      </g>
      <circle cx="1270" cy="90" r="100" fill="#E8E1CF" opacity="0.04" />
      <circle cx="1270" cy="90" r="40" fill="#E8E1CF" />
      <path
        d="M0 220 C260 190 520 204 760 210 C1000 216 1200 186 1440 196 V420 H0 Z"
        fill="#171B23"
      />
      <g fill="#1F242C" stroke="#2A3039">
        <path d="M180 222 V196 A13 13 0 0 1 206 196 V222 Z" />
        <path d="M1060 214 V190 A12 12 0 0 1 1084 190 V214 Z" />
        <path d="M1180 206 V184 A11 11 0 0 1 1202 184 V206 Z" />
      </g>
      <rect x="0" y="262" width="1440" height="158" fill="#2A2219" />
      <rect x="0" y="262" width="1440" height="10" fill="#1F2A21" />
      <path
        d="M0 312 C300 304 600 318 900 310 C1100 304 1300 314 1440 308"
        stroke="#33291E"
        strokeWidth="10"
        fill="none"
      />
      <path
        d="M0 360 C320 352 640 368 960 358 C1160 352 1320 362 1440 356"
        stroke="#231C14"
        strokeWidth="12"
        fill="none"
      />
      <rect x="610" y="262" width="230" height="140" fill="#0B0A08" />
      <path d="M610 262 V402 H840 V262" fill="none" stroke="#3A2E22" strokeWidth="4" />
      <rect x="630" y="370" width="190" height="26" rx="4" fill="#3B2A1C" stroke="#5A4330" />
      <path d="M700 383 H750 M725 372 V394" stroke="#5A4330" strokeWidth="3" />
      <rect
        className="gy-backfill"
        data-testid="backfill"
        x={PIT.x + 2}
        y={PIT.top + PIT.height * d}
        width={PIT.width - 4}
        height={PIT.height * (1 - d)}
        fill="#2A2219"
      />
      <path d="M380 262 C420 190 470 168 520 170 C566 172 590 210 604 262 Z" fill="#3A2E22" />
      <path d="M420 262 C450 214 486 200 516 202 C546 204 568 230 580 262 Z" fill="#46382A" />
      <g className="gy-dirt">
        <circle cx="640" cy="250" r="5" fill="#46382A" />
        <circle cx="652" cy="242" r="3.5" fill="#3A2E22" />
      </g>
      <g className="gy-dirt2">
        <circle cx="660" cy="256" r="4" fill="#46382A" />
        <circle cx="646" cy="246" r="3" fill="#3A2E22" />
      </g>
      <path d="M520 104 L494 196" stroke="#B8B2A5" strokeWidth="6" strokeLinecap="round" />
      <path d="M510 96 H534" stroke="#B8B2A5" strokeWidth="6" strokeLinecap="round" />
      <path d="M484 190 L506 196 L498 226 L476 220 Z" fill="#8F96A0" />
      <g>
        <g className="gy-flame">
          <ellipse cx="900" cy="234" rx="110" ry="70" fill="#E9B266" opacity="0.13" />
        </g>
        <path d="M890 262 H910 V252 H890 Z" fill="#14171C" />
        <path d="M886 252 H914 L910 222 H890 Z" fill="#14171C" stroke="#E9B266" strokeWidth="1.4" />
        <path
          className="gy-flame"
          d="M900 230 C906 236 906 246 900 248 C894 246 894 236 900 230 Z"
          fill="#F3C77C"
        />
        <path
          d="M892 222 C892 212 908 212 908 222"
          fill="none"
          stroke="#E9B266"
          strokeWidth="1.6"
        />
      </g>
      <path
        className="gy-fog3"
        d="M-200 250 C100 226 300 262 600 244 C900 228 1100 266 1640 240 V280 H-200 Z"
        fill="#CBD2DE"
        opacity="0.06"
      />
    </svg>
  );
}
