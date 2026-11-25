/** The six states and overlays of the design system (frontend-design.md section 5). */
export const STATE_KEYS = ['dead', 'cursed', 'ailing', 'resting', 'alive', 'wounded'] as const;
export type StateKey = (typeof STATE_KEYS)[number];

/** Themed word and plain term, always shown together where a state is named (PRD section 6). */
export const STATE_TERMS: Record<StateKey, { themed: string; plain: string }> = {
  alive: { themed: 'Alive', plain: 'healthy' },
  resting: { themed: 'Resting', plain: 'dormant, stable' },
  ailing: { themed: 'Ailing', plain: 'at risk' },
  dead: { themed: 'Dead', plain: 'abandoned' },
  cursed: { themed: 'Cursed', plain: 'unfixable vulnerability' },
  wounded: { themed: 'Wounded', plain: 'fixable vulnerability' },
};
