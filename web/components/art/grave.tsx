export type GraveType = 'cursed' | 'dead' | 'ailing' | 'resting' | 'wounded' | 'alive';

/**
 * The graves of the scene (viewBox 120 by 160), ported from Graveyard.dc.html. `alive` is the wounded sapling
 * without the bandage (the scene draws no alive grave). Decorative: the link around it carries the name.
 */
export function Grave({
  type,
  width,
  className,
}: {
  type: GraveType;
  width: number;
  className?: string;
}) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width={width}
      height={Math.round((width * 160) / 120)}
      viewBox="0 0 120 160"
      className={className}
    >
      {type === 'cursed' && (
        <>
          {/* The animation sits on the group: on the ellipse it would replace the ellipse's own opacity. */}
          <g className="gy-glow">
            <ellipse cx="60" cy="86" rx="58" ry="74" fill="#C4AEF5" opacity="0.18" />
          </g>
          <ellipse cx="60" cy="152" rx="50" ry="7" fill="#2A2233" />
          <path
            d="M40 152 L48 34 L60 8 L72 34 L80 152 Z"
            fill="#2B2838"
            stroke="#C4AEF5"
            strokeWidth="1.6"
          />
          <path d="M60 70 l5 12 12 4 -12 4 -5 12 -5 -12 -12 -4 12 -4 z" fill="#C4AEF5" />
        </>
      )}
      {type === 'dead' && (
        <>
          <ellipse cx="60" cy="150" rx="58" ry="10" fill="#3A2E22" />
          <path
            d="M16 148 V62 A44 44 0 0 1 104 62 V148 Z"
            fill="#2A2F37"
            stroke="#E8887B"
            strokeWidth="1.4"
          />
          <path d="M60 38 V92 M42 56 H78" stroke="#E8887B" strokeWidth="5" />
        </>
      )}
      {type === 'ailing' && (
        <>
          <ellipse cx="60" cy="152" rx="54" ry="8" fill="#2C2A22" />
          <g transform="rotate(-7 60 150)">
            <path
              d="M18 150 V58 Q18 42 34 42 H86 Q102 42 102 58 V150 Z"
              fill="#2A2F37"
              stroke="#E9B266"
              strokeWidth="1.4"
            />
            <path d="M82 42 L70 70 L82 88 L66 118" fill="none" stroke="#E9B266" strokeWidth="2" />
          </g>
        </>
      )}
      {type === 'resting' && (
        <>
          <ellipse cx="60" cy="152" rx="54" ry="8" fill="#1F2A21" />
          <path
            d="M18 150 V64 A42 42 0 0 1 102 64 V150 Z"
            fill="#2A2F37"
            stroke="#8FB2E0"
            strokeWidth="1.4"
          />
          <path d="M70 66 A14 14 0 1 1 56 52 A11 11 0 0 0 70 66 Z" fill="#8FB2E0" />
          <circle cx="26" cy="148" r="4" fill="#93CBA6" />
          <circle cx="35" cy="150" r="3.4" fill="#E8E1CF" />
          <circle cx="92" cy="148" r="4" fill="#8FB2E0" />
          <circle cx="84" cy="150" r="3" fill="#93CBA6" />
        </>
      )}
      {(type === 'wounded' || type === 'alive') && (
        <>
          <ellipse cx="60" cy="152" rx="50" ry="7" fill="#1F2A21" />
          <path d="M60 152 V70" stroke="#93CBA6" strokeWidth="4" />
          <path d="M60 104 C38 100 26 84 26 64 C48 64 60 82 60 104 Z" fill="#93CBA6" />
          <path d="M60 90 C80 84 92 64 94 48 C72 48 60 68 60 90 Z" fill="#6FA982" />
          {type === 'wounded' && (
            <rect
              x="46"
              y="112"
              width="28"
              height="10"
              rx="3"
              fill="#F0A39A"
              transform="rotate(-20 60 117)"
            />
          )}
        </>
      )}
    </svg>
  );
}
