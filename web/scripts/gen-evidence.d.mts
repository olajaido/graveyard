export interface Evidence {
  deadPrecision: {
    num: number;
    den: number;
    wilsonLow: number;
    wilsonHigh: number;
    passedThreshold: boolean;
  };
  verdictPassed: boolean;
  floorsMet: boolean;
  modelVersion: string;
  asOf: string;
}
export const SOURCE: string;
export const TARGET: string;
export function extractEvidence(result: unknown): Evidence;
