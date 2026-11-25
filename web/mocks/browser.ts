import { setupWorker } from 'msw/browser';
import { createMockApi, defaultWorld, type Script } from './handlers';
import { completeScan, runningScan } from './fixtures/builders';
import { hauntedGraves, HAUNTED_SCAN_ID } from './fixtures/haunted-house';
import { minimalCertificate, manyGraves } from './fixtures/builders';
import type { Certificate } from '@/lib/api/types';

/** The scripted scan of the e2e build: every stage, `AUTOPSY` with moving progress, then COMPLETE (design 15). */
export function e2eScript(): Script {
  const total = 208;
  return [
    runningScan('QUEUED'),
    runningScan('VALIDATE'),
    runningScan('FETCH'),
    runningScan('SBOM'),
    runningScan('GRAPH'),
    runningScan('AUTOPSY', { examined: 0, total }),
    runningScan('AUTOPSY', { examined: 104, total }),
    runningScan('AUTOPSY', { examined: 208, total }),
    runningScan('CLASSIFY'),
    completeScan(),
  ];
}

/** A second scan that is already complete, for the tests that open a results or a certificate link directly. */
export const E2E_DONE_SCAN_ID = '01M84GKAYX7D2JGJ1PYN5JGSS7-aaaaaaaaaaaaaaaa';
/** A scoped npm package in that scan, so the double encoding of its purl is tested in a real browser. */
export const E2E_SCOPED_PURL = 'pkg:npm/%40babel/core@7.0.0';

/** Only the e2e build imports this file (`NEXT_PUBLIC_API_MOCKING=enabled`). The production build never does. */
export async function startMockWorker(): Promise<void> {
  const scoped = { ...manyGraves(1)[0]!, purl: E2E_SCOPED_PURL, priority: 1, via: null };
  const doneScan = completeScan({ scanId: E2E_DONE_SCAN_ID });
  const certificates: Record<string, Record<string, Certificate>> = {
    [HAUNTED_SCAN_ID]: {},
    [E2E_DONE_SCAN_ID]: { [E2E_SCOPED_PURL]: minimalCertificate(scoped) },
  };
  const api = createMockApi({
    scans: { [HAUNTED_SCAN_ID]: e2eScript(), [E2E_DONE_SCAN_ID]: doneScan },
    graves: {
      [HAUNTED_SCAN_ID]: hauntedGraves.items,
      [E2E_DONE_SCAN_ID]: [...hauntedGraves.items, scoped],
    },
    certificates: {
      ...certificates,
      [E2E_DONE_SCAN_ID]: {
        ...certificates[E2E_DONE_SCAN_ID],
        ...defaultWorld().certificates[HAUNTED_SCAN_ID],
      },
      [HAUNTED_SCAN_ID]: defaultWorld().certificates[HAUNTED_SCAN_ID] ?? {},
    },
  });
  await setupWorker(...api.handlers).start({ onUnhandledFrame: 'bypass', quiet: true });
}
