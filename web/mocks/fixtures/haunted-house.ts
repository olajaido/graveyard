import type { Certificate, GravePage, Scan } from '@/lib/api/types';
import gravesJson from '@/content/haunted-house/graves.json';
import lodashJson from '@/content/haunted-house/grave-lodash.template.json';
import scanJson from '@/content/haunted-house/scan.json';

/**
 * The captured responses of a real scan of olajaido/haunted-house (model v2, group B deployed; recaptured by the
 * maintainer, design/fixtures/haunted-house/). They are typed here once, so a field the API drops or renames breaks
 * the type check of every test that uses them.
 */
export const hauntedScan = scanJson as Scan;
export const hauntedGraves = gravesJson as GravePage;
export const lodashCertificate = lodashJson as Certificate;
export const HAUNTED_SCAN_ID = hauntedScan.scanId;
