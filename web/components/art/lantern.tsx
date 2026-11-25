export type LanternState = 'lit' | 'working' | 'unlit';

/** One lantern of the lantern path (64 by 90). Ported from Exhumation.dc.html. Decorative. */
export function Lantern({ state, className }: { state: LanternState; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="64"
      height="90"
      viewBox="0 0 64 90"
      className={className}
    >
      {state === 'lit' && (
        <>
          <ellipse cx="32" cy="34" rx="30" ry="30" fill="#E9B266" opacity="0.16" />
          <path d="M30 46 H34 V88 H30 Z" fill="#3A3F45" />
          <path d="M22 18 H42 L40 46 H24 Z" fill="#14171C" stroke="#E9B266" strokeWidth="1.4" />
          <path d="M32 24 C37 30 37 38 32 40 C27 38 27 30 32 24 Z" fill="#F3C77C" />
          <path d="M26 18 C26 10 38 10 38 18" fill="none" stroke="#E9B266" strokeWidth="1.6" />
        </>
      )}
      {state === 'working' && (
        <>
          <g className="gy-flame">
            <ellipse cx="32" cy="34" rx="31" ry="31" fill="#E9B266" opacity="0.28" />
          </g>
          <path d="M30 46 H34 V88 H30 Z" fill="#3A3F45" />
          <path d="M22 18 H42 L40 46 H24 Z" fill="#14171C" stroke="#F3C77C" strokeWidth="1.8" />
          <path
            className="gy-flame"
            d="M32 22 C38 29 38 38 32 41 C26 38 26 29 32 22 Z"
            fill="#F3C77C"
          />
          <path d="M26 18 C26 10 38 10 38 18" fill="none" stroke="#F3C77C" strokeWidth="1.8" />
        </>
      )}
      {state === 'unlit' && (
        <>
          <path d="M30 46 H34 V88 H30 Z" fill="#2A2F37" />
          <path d="M22 18 H42 L40 46 H24 Z" fill="#14171C" stroke="#4A505A" strokeWidth="1.4" />
          <path d="M26 18 C26 10 38 10 38 18" fill="none" stroke="#4A505A" strokeWidth="1.6" />
        </>
      )}
    </svg>
  );
}
