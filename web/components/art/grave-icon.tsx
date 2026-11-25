import type { GraveType } from './grave';

/** The six 80 by 90 graves of the "Six states of being" cards. Ported from Main.dc.html. Decorative. */
export function GraveIcon({ type, className }: { type: GraveType; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="80"
      height="90"
      viewBox="0 0 80 90"
      className={className}
    >
      {(type === 'alive' || type === 'wounded') && (
        <>
          <ellipse cx="40" cy="84" rx="34" ry="5" fill="#1F2A21" />
          <path d="M40 84 V40" stroke="#93CBA6" strokeWidth="3" />
          <path d="M40 54 C26 52 18 42 18 30 C32 30 40 40 40 54 Z" fill="#93CBA6" />
          <path d="M40 46 C52 42 60 30 62 20 C48 20 40 32 40 46 Z" fill="#6FA982" />
          {type === 'wounded' && (
            <rect
              x="31"
              y="58"
              width="18"
              height="7"
              rx="2"
              fill="#F0A39A"
              transform="rotate(-20 40 61)"
            />
          )}
        </>
      )}
      {type === 'resting' && (
        <>
          <path d="M14 86 V36 A26 26 0 0 1 66 36 V86 Z" fill="#2A2F37" stroke="#8FB2E0" />
          <path d="M46 30 A10 10 0 1 1 36 20 A8 8 0 0 0 46 30 Z" fill="#8FB2E0" />
          <circle cx="20" cy="84" r="3" fill="#93CBA6" />
          <circle cx="27" cy="85" r="2.5" fill="#E8E1CF" />
          <circle cx="60" cy="84" r="3" fill="#8FB2E0" />
        </>
      )}
      {type === 'ailing' && (
        <g transform="rotate(-8 40 86)">
          <path
            d="M14 86 V32 Q14 22 24 22 H56 Q66 22 66 32 V86 Z"
            fill="#2A2F37"
            stroke="#E9B266"
          />
          <path d="M50 22 L42 40 L50 52 L40 72" fill="none" stroke="#E9B266" strokeWidth="1.6" />
        </g>
      )}
      {type === 'dead' && (
        <>
          <ellipse cx="40" cy="84" rx="36" ry="6" fill="#3A2E22" />
          <path d="M14 84 V36 A26 26 0 0 1 66 36 V84 Z" fill="#2A2F37" stroke="#E8887B" />
          <path d="M40 24 V58 M28 36 H52" stroke="#E8887B" strokeWidth="3" />
        </>
      )}
      {type === 'cursed' && (
        <>
          <ellipse cx="40" cy="50" rx="34" ry="40" fill="#C4AEF5" opacity="0.12" />
          <path d="M28 88 L34 20 L40 8 L46 20 L52 88 Z" fill="#2B2838" stroke="#C4AEF5" />
          <path d="M40 40 l4 9 9 3 -9 3 -4 9 -4 -9 -9 -3 9 -3 z" fill="#C4AEF5" />
        </>
      )}
    </svg>
  );
}
