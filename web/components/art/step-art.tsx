export type Step = 'exhume' | 'identify' | 'trace' | 'pronounce';

/** The four "how it works" illustrations (140 by 100). Ported from Main.dc.html. Decorative. */
export function StepArt({ step, className }: { step: Step; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="140"
      height="100"
      viewBox="0 0 140 100"
      className={className}
    >
      {step === 'exhume' && (
        <>
          <ellipse cx="70" cy="88" rx="64" ry="9" fill="#1A150F" />
          <path d="M18 88 C30 62 54 56 70 58 C88 60 110 70 122 88 Z" fill="#3A2E22" />
          <path d="M92 10 L78 66" stroke="#B8B2A5" strokeWidth="4" strokeLinecap="round" />
          <path d="M70 62 L86 66 L80 84 L64 80 Z" fill="#8F96A0" />
          <path d="M86 6 H100" stroke="#B8B2A5" strokeWidth="4" strokeLinecap="round" />
          <rect
            x="36"
            y="44"
            width="16"
            height="20"
            rx="2"
            fill="#ECE6D8"
            transform="rotate(-14 44 54)"
          />
          <path
            d="M40 50 H48 M40 54 H48 M40 58 H46"
            stroke="#2A2F37"
            strokeWidth="1.4"
            transform="rotate(-14 44 54)"
          />
        </>
      )}
      {step === 'identify' && (
        <>
          <rect x="14" y="70" width="112" height="18" rx="4" fill="#2A2F37" />
          <path
            d="M30 79 h20 M58 79 h28 M94 79 h18"
            stroke="#ECE6D8"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <path d="M40 30 l16 8 -6 12 -16 -8 z" fill="#ECE6D8" />
          <circle cx="38" cy="34" r="3" fill="#2A2F37" />
          <path d="M56 38 L72 52" stroke="#ECE6D8" strokeWidth="1.6" strokeDasharray="3 3" />
          <circle cx="92" cy="34" r="22" fill="#161A21" stroke="#B8B2A5" strokeWidth="4" />
          <circle cx="92" cy="34" r="14" fill="#E8E1CF" opacity="0.12" />
          <path d="M108 50 L124 66" stroke="#B8B2A5" strokeWidth="6" strokeLinecap="round" />
        </>
      )}
      {step === 'trace' && (
        <>
          <path d="M0 40 H140" stroke="#3A3F45" strokeWidth="2" />
          <rect x="58" y="12" width="24" height="28" rx="10" fill="#2A2F37" stroke="#8F96A0" />
          <g stroke="#8F96A0" strokeWidth="2" fill="none" strokeLinecap="round">
            <path d="M70 40 V58" />
            <path d="M70 58 C56 64 40 66 28 80" />
            <path d="M70 58 C84 64 100 66 112 80" />
            <path d="M70 58 V86" />
            <path d="M40 70 C34 74 30 80 30 92" />
            <path d="M102 70 C108 76 110 82 108 92" />
          </g>
          <circle cx="28" cy="80" r="6" fill="#E8887B" />
          <circle cx="112" cy="80" r="6" fill="#93CBA6" />
          <circle cx="70" cy="86" r="6" fill="#E9B266" />
          <circle cx="30" cy="92" r="4" fill="#C4AEF5" />
        </>
      )}
      {step === 'pronounce' && (
        <>
          <rect x="22" y="10" width="72" height="84" rx="3" fill="#EDE6D6" />
          <path d="M32 26 H84 M32 36 H76 M32 46 H80 M32 56 H64" stroke="#B4AA94" strokeWidth="2" />
          <circle cx="96" cy="68" r="26" fill="#8A2B1F" />
          <circle cx="96" cy="68" r="19" fill="none" stroke="#B8463A" strokeWidth="2" />
          <text
            x="96"
            y="73"
            textAnchor="middle"
            fontFamily="Cormorant Garamond, Georgia, serif"
            fontWeight="700"
            fontSize="14"
            fill="#F2D6CF"
          >
            DEAD
          </text>
        </>
      )}
    </svg>
  );
}
