import { useId } from 'react';

/** A unique, selector-safe id for an SVG pattern or gradient, so two copies on one page never collide. */
export function useSvgId(prefix: string): string {
  return `${prefix}${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
}
