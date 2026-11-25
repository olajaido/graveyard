import { useSvgId } from './use-svg-id';

/**
 * The landing hero: night sky, moon, hills, chapel, fence, dead tree, graves and fog. Ported from Main.dc.html with
 * the shapes and colours unchanged. The package names are illustration, not data. Decorative.
 */
export function NightScene({ className }: { className?: string }) {
  const picket = useSvgId('gyPicket');
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 1440 640"
      preserveAspectRatio="xMidYMax slice"
      className={className}
    >
      <g fill="#E8E1CF">
        <circle className="gy-star" cx="80" cy="60" r="1.4" />
        <circle cx="190" cy="140" r="1" />
        <circle cx="310" cy="40" r="1.2" />
        <circle className="gy-star" cx="420" cy="110" r="1.6" />
        <circle cx="560" cy="50" r="1" />
        <circle cx="640" cy="160" r="1.3" />
        <circle className="gy-star" cx="760" cy="70" r="1.1" />
        <circle cx="880" cy="30" r="1.5" />
        <circle cx="960" cy="130" r="1" />
        <circle cx="1290" cy="60" r="1.2" />
        <circle className="gy-star" cx="1380" cy="150" r="1.4" />
        <circle cx="1240" cy="250" r="1" />
        <circle cx="1020" cy="220" r="1.1" />
        <circle cx="700" cy="250" r="1" />
      </g>
      <circle cx="1130" cy="150" r="150" fill="#E8E1CF" opacity="0.035" />
      <circle cx="1130" cy="150" r="96" fill="#E8E1CF" opacity="0.06" />
      <circle cx="1130" cy="150" r="58" fill="#E8E1CF" />
      <circle cx="1112" cy="136" r="9" fill="#D7CFBB" />
      <circle cx="1146" cy="168" r="12" fill="#D7CFBB" />
      <circle cx="1150" cy="128" r="5" fill="#D7CFBB" />
      <path
        d="M0 430 C200 380 380 400 560 420 C760 440 900 360 1100 380 C1250 395 1350 370 1440 360 V640 H0 Z"
        fill="#1A1F29"
      />
      <path
        d="M1220 384 V330 H1236 V306 L1252 280 L1268 306 V330 H1284 V384 Z M1252 262 V280 M1246 268 H1258"
        fill="#161A22"
        stroke="#161A22"
        strokeWidth="3"
      />
      <path
        d="M0 500 C240 450 520 470 760 485 C980 500 1180 440 1440 455 V640 H0 Z"
        fill="#141820"
      />
      <defs>
        <pattern id={picket} width="20" height="56" patternUnits="userSpaceOnUse">
          <path d="M10 2 L14 11 L10 9 L6 11 Z" fill="#0B0D11" />
          <rect x="8.6" y="9" width="2.8" height="47" fill="#0B0D11" />
        </pattern>
      </defs>
      <rect x="560" y="430" width="420" height="56" fill={`url(#${picket})`} />
      <rect x="560" y="446" width="420" height="3" fill="#0B0D11" />
      <rect x="560" y="472" width="420" height="3" fill="#0B0D11" />
      <g fill="#1F242C" stroke="#2A3039" strokeWidth="1">
        <path d="M690 492 V470 A12 12 0 0 1 714 470 V492 Z" />
        <path d="M790 496 V474 A11 11 0 0 1 812 474 V496 Z" />
        <path d="M1050 486 V462 A13 13 0 0 1 1076 462 V486 Z" />
        <path d="M1180 478 V458 A11 11 0 0 1 1202 458 V478 Z" />
        <path d="M1316 472 V452 A10 10 0 0 1 1336 452 V472 Z" />
      </g>
      <g stroke="#0A0C0F" strokeLinecap="round" fill="none">
        <path d="M150 600 C146 520 152 470 140 420" strokeWidth="14" />
        <path d="M142 470 C110 440 96 420 70 410" strokeWidth="7" />
        <path d="M144 440 C176 410 196 380 230 366" strokeWidth="7" />
        <path d="M140 420 C130 380 120 360 128 320" strokeWidth="6" />
        <path d="M86 416 C70 396 60 390 44 392" strokeWidth="3" />
        <path d="M200 382 C214 360 222 350 240 344" strokeWidth="3" />
        <path d="M128 340 C108 320 100 306 98 290" strokeWidth="3" />
        <path d="M130 330 C150 312 158 300 166 284" strokeWidth="3" />
      </g>
      <path
        d="M0 560 C300 528 600 546 900 540 C1150 536 1300 518 1440 528 V640 H0 Z"
        fill="#0D0F13"
      />
      <g className="gy-glow">
        <ellipse cx="960" cy="420" rx="90" ry="140" fill="#C4AEF5" opacity="0.07" />
        <ellipse cx="960" cy="440" rx="54" ry="100" fill="#C4AEF5" opacity="0.09" />
      </g>
      <g fontFamily="JetBrains Mono, monospace" fontSize="11" fill="#9AA0AA" textAnchor="middle">
        <ellipse cx="680" cy="560" rx="62" ry="9" fill="#1A150F" />
        <path d="M630 556 V482 A50 50 0 0 1 730 482 V556 Z" fill="#2A2F37" stroke="#3E444E" />
        <path d="M680 456 V498 M664 470 H696" stroke="#1D2127" strokeWidth="4" />
        <text x="680" y="526">
          gulp-util
        </text>
        <text x="680" y="541" fontSize="9" fill="#7E848E">
          3.0.8
        </text>
        <ellipse cx="820" cy="556" rx="52" ry="8" fill="#1A150F" />
        <path
          d="M806 552 V478 H784 V458 H806 V434 H834 V458 H856 V478 H834 V552 Z"
          fill="#2A2F37"
          stroke="#3E444E"
        />
        <text x="820" y="512" fontSize="10">
          request
        </text>
        <path
          d="M928 556 L940 330 L960 300 L980 330 L992 556 Z"
          fill="#2B2838"
          stroke="#C4AEF5"
          strokeWidth="1.4"
        />
        <path
          d="M960 380 L966 396 L982 400 L966 406 L960 422 L954 406 L938 400 L954 396 Z"
          fill="none"
          stroke="#C4AEF5"
          strokeWidth="1.4"
        />
        <text x="960" y="470" fontSize="10" fill="#C4AEF5">
          lodash.
        </text>
        <text x="960" y="484" fontSize="10" fill="#C4AEF5">
          template
        </text>
        <ellipse cx="1090" cy="560" rx="58" ry="9" fill="#1A150F" />
        <path
          d="M1044 556 V494 Q1044 470 1068 470 H1112 Q1136 470 1136 494 V556 Z"
          fill="#2A2F37"
          stroke="#3E444E"
        />
        <text x="1090" y="520">
          tslint
        </text>
        <text x="1090" y="535" fontSize="9" fill="#7E848E">
          6.1.3
        </text>
        <g transform="rotate(-7 1230 556)">
          <path d="M1186 556 V490 A44 44 0 0 1 1274 490 V556 Z" fill="#2A2F37" stroke="#3E444E" />
          <path
            d="M1246 470 L1238 492 L1248 506 L1236 528"
            fill="none"
            stroke="#1A1D22"
            strokeWidth="2"
          />
          <text x="1230" y="530" fontSize="10">
            coffee-script
          </text>
        </g>
        <ellipse cx="1360" cy="556" rx="50" ry="8" fill="#1A150F" />
        <path d="M1322 552 V490 A38 38 0 0 1 1398 490 V552 Z" fill="#2A2F37" stroke="#3E444E" />
        <text x="1360" y="522">
          argparse
        </text>
      </g>
      <path
        className="gy-fog1"
        d="M-200 560 C100 520 300 580 600 548 C900 520 1100 590 1500 540 C1600 530 1700 560 1700 600 H-200 Z"
        fill="#CBD2DE"
        opacity="0.06"
      />
      <path
        className="gy-fog2"
        d="M-200 600 C200 570 500 610 800 586 C1100 566 1300 612 1700 584 V640 H-200 Z"
        fill="#CBD2DE"
        opacity="0.07"
      />
    </svg>
  );
}
