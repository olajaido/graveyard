import type { components } from './schema';

type Schemas = components['schemas'];

export type Scan = Schemas['Scan'];
export type ScanAccepted = Schemas['ScanAccepted'];
export type Counts = Schemas['Counts'];
export type Service = Schemas['Service'];
export type Progress = Schemas['Progress'];
export type ErrorCode = Schemas['ErrorCode'];
export type Stage = Schemas['Stage'];
export type GraveSummary = Schemas['GraveSummary'];
export type GravePage = Schemas['GravePage'];
export type Certificate = Schemas['Certificate'];
export type EvidenceLink = Schemas['EvidenceLink'];
export type EvidenceItem = Schemas['EvidenceItem'];
export type Evidence = Schemas['Evidence'];
export type ExamplePath = Schemas['ExamplePath'];
export type Problem = Schemas['Problem'];
export type EvidenceKey = keyof Evidence;
