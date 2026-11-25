import type { StateKey } from '@/lib/model/state-key';

// Full class names, so Tailwind can see them.
/** Text, on parchment: state ink on state pill. */
export const PILL_CLASS: Record<StateKey, string> = {
  dead: 'bg-dead-pill text-dead-ink',
  cursed: 'bg-cursed-pill text-cursed-ink',
  ailing: 'bg-ailing-pill text-ailing-ink',
  resting: 'bg-resting-pill text-resting-ink',
  alive: 'bg-alive-pill text-alive-ink',
  wounded: 'bg-wounded-pill text-wounded-ink',
};
/** Text, on parchment, no background. */
export const INK_CLASS: Record<StateKey, string> = {
  dead: 'text-dead-ink',
  cursed: 'text-cursed-ink',
  ailing: 'text-ailing-ink',
  resting: 'text-resting-ink',
  alive: 'text-alive-ink',
  wounded: 'text-wounded-ink',
};
/** Text, on dark surfaces: the bright colour. */
export const BRIGHT_CLASS: Record<StateKey, string> = {
  dead: 'text-dead',
  cursed: 'text-cursed',
  ailing: 'text-ailing',
  resting: 'text-resting',
  alive: 'text-alive',
  wounded: 'text-wounded',
};
export const DOT_CLASS: Record<StateKey, string> = {
  dead: 'bg-dead',
  cursed: 'bg-cursed',
  ailing: 'bg-ailing',
  resting: 'bg-resting',
  alive: 'bg-alive',
  wounded: 'bg-wounded',
};
/** The ink as a CSS value, for SVG strokes (toe tags). */
export const INK_VAR: Record<StateKey, string> = {
  dead: 'var(--color-dead-ink)',
  cursed: 'var(--color-cursed-ink)',
  ailing: 'var(--color-ailing-ink)',
  resting: 'var(--color-resting-ink)',
  alive: 'var(--color-alive-ink)',
  wounded: 'var(--color-wounded-ink)',
};
