export const FORBIDDEN: { pattern: RegExp; why: string }[];
export function check(dir: string): string[];
export function cspProblems(html: string): string[];
