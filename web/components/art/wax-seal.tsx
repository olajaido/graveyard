export type SealTone = 'dead' | 'cursed' | 'ailing' | 'resting' | 'alive' | 'wounded';

/** Dead keeps the colours of the mockup. The other states take their ink, bright colour and a darkened ink (design D10). */
const PALETTE: Record<SealTone, { fill: string; ring: string; inner: string }> = {
  dead: { fill: '#8A2B1F', ring: '#B8463A', inner: '#6E2118' },
  cursed: tone('--color-cursed-ink', '--color-cursed'),
  ailing: tone('--color-ailing-ink', '--color-ailing'),
  resting: tone('--color-resting-ink', '--color-resting'),
  alive: tone('--color-alive-ink', '--color-alive'),
  wounded: tone('--color-wounded-ink', '--color-wounded'),
};

function tone(ink: string, bright: string) {
  return {
    fill: `var(${ink})`,
    ring: `var(${bright})`,
    inner: `color-mix(in srgb, var(${ink}) 70%, black)`,
  };
}

/**
 * The wax seal of the certificate (96 by 96), ported from Certificate.dc.html. Decorative: the page already says
 * the state in words. `word` is the state word ("DECEASED"), `date` the issue date in seal form ("22·XI·2026").
 */
export function WaxSeal({
  word,
  date,
  tone: seal = 'dead',
  className,
}: {
  word: string;
  date: string;
  tone?: SealTone;
  className?: string;
}) {
  const colors = PALETTE[seal];
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="96"
      height="96"
      viewBox="0 0 96 96"
      style={{ transform: 'rotate(-12deg)' }}
      className={className}
    >
      <path
        d="M48 4 C58 6 62 2 70 8 C78 14 84 12 88 22 C92 30 96 34 92 44 C90 52 94 58 88 66 C82 74 82 80 72 84 C64 88 60 94 50 92 C40 92 36 96 28 90 C20 84 14 86 10 76 C6 68 2 64 4 54 C6 46 0 40 6 32 C10 24 10 18 20 12 C28 6 36 4 48 4 Z"
        fill={colors.fill}
      />
      <circle cx="48" cy="48" r="32" fill="none" stroke={colors.ring} strokeWidth="2" />
      <circle cx="48" cy="48" r="27" fill="none" stroke={colors.inner} strokeWidth="1" />
      <text
        x="48"
        y="45"
        textAnchor="middle"
        fontFamily="Cormorant Garamond, Georgia, serif"
        fontWeight="700"
        fontSize="13"
        fill="#F2D6CF"
        letterSpacing="1"
      >
        {word}
      </text>
      <text
        x="48"
        y="60"
        textAnchor="middle"
        fontFamily="Cormorant Garamond, Georgia, serif"
        fontStyle="italic"
        fontSize="11"
        fill="#F2D6CF"
      >
        {date}
      </text>
    </svg>
  );
}
