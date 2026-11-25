import type { View } from '@/lib/model/route';

const ICON = {
  scene: (
    <svg
      width="16"
      height="18"
      viewBox="0 0 28 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M3 31V13a11 11 0 0 1 22 0v18" />
      <path d="M1 31h26" />
    </svg>
  ),
  table: (
    <svg
      width="16"
      height="18"
      viewBox="0 0 16 18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M5 2h6M8 2v2" />
      <path d="M3 6h10l-1 9H4z" />
      <path d="M8 8v4" />
    </svg>
  ),
};

/** "Graveyard" and "Lights on", always visible (ui-core UI-GY-10). Two toggle buttons in one group. */
export function ViewToggle({ value, onChange }: { value: View; onChange: (next: View) => void }) {
  const button = (view: View, label: string) => (
    <button
      type="button"
      aria-pressed={value === view}
      onClick={() => onChange(view)}
      className={`inline-flex h-11 cursor-pointer items-center gap-2 rounded-[9px] border-0 px-4 text-[15px] font-semibold ${
        value === view ? 'bg-bone text-on-bone' : 'bg-transparent text-bone-muted hover:text-bone'
      }`}
    >
      {ICON[view]}
      {label}
    </button>
  );
  return (
    <div
      role="group"
      aria-label="View"
      className="inline-flex gap-1 rounded-[12px] border border-surface-line bg-surface p-1"
    >
      {button('scene', 'Graveyard')}
      {button('table', 'Lights on')}
    </div>
  );
}
