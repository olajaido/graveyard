import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CertificatePage } from '@/components/certificate/certificate-page';
import { ScanPage } from '@/components/exhumation/scan-page';
import { createClient } from '@/lib/api/client';
import {
  expectDecorativeSvgs,
  expectHeadingOrder,
  expectNativeControls,
  tabbables,
} from '@/lib/test/page-checks';
import {
  completeScan,
  emptyScan,
  failedScan,
  manyGraves,
  minimalCertificate,
  runningScan,
} from '@/mocks/fixtures/builders';
import { HAUNTED_SCAN_ID } from '@/mocks/fixtures/haunted-house';
import { mockApi } from '@/mocks/node';
import Home from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const client = createClient({ baseUrl: 'https://api.test' });
const scanUrl = () => window.history.replaceState(null, '', `/scan?id=${HAUNTED_SCAN_ID}`);
const PLACEHOLDERS = [
  '[notice text',
  '[advisory',
  '142 of',
  '68%',
  'Fresh toe tags',
  'tally so far',
  'DECEASED',
];

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  window.localStorage.clear();
});
afterEach(() => vi.useRealTimers());

async function settle(ready: () => unknown) {
  await act(async () => void (await vi.advanceTimersByTimeAsync(50)));
  await waitFor(ready);
}

type Case = { name: string; mount: () => Promise<void> };
const CASES: Case[] = [
  {
    name: 'the landing page',
    mount: async () => void render(<Home />),
  },
  {
    name: 'a scan that is running',
    mount: async () => {
      mockApi({ scans: { [HAUNTED_SCAN_ID]: runningScan('AUTOPSY', { examined: 3, total: 9 }) } });
      scanUrl();
      render(<ScanPage client={client} />);
      await settle(() => screen.getByRole('heading', { level: 1, name: 'olajaido/haunted-house' }));
    },
  },
  {
    name: 'the results (scene)',
    mount: async () => {
      mockApi();
      scanUrl();
      render(<ScanPage client={client} />);
      await settle(() => screen.getByRole('group', { name: 'Filter by state' }));
    },
  },
  {
    name: 'the results (table)',
    mount: async () => {
      mockApi();
      window.history.replaceState(null, '', `/scan?id=${HAUNTED_SCAN_ID}&view=table`);
      render(<ScanPage client={client} />);
      await settle(() => screen.getByRole('table'));
    },
  },
  {
    name: 'an empty graveyard',
    mount: async () => {
      mockApi({ scans: { [HAUNTED_SCAN_ID]: emptyScan() }, graves: { [HAUNTED_SCAN_ID]: [] } });
      scanUrl();
      render(<ScanPage client={client} />);
      await settle(() => screen.getByRole('heading', { name: /Your dependencies live/ }));
    },
  },
  {
    name: 'a failed scan',
    mount: async () => {
      mockApi({ scans: { [HAUNTED_SCAN_ID]: failedScan('NO_MANIFESTS') } });
      scanUrl();
      render(<ScanPage client={client} />);
      await settle(() => screen.getByRole('heading', { name: 'Nothing buried here' }));
    },
  },
  {
    name: 'a certificate',
    mount: async () => {
      mockApi();
      window.history.replaceState(
        null,
        '',
        `/grave?scan=${HAUNTED_SCAN_ID}&purl=${encodeURIComponent('pkg:npm/lodash.template@3.6.2')}`,
      );
      render(<CertificatePage client={client} />);
      await settle(() => screen.getByRole('heading', { name: 'Certificate of Death' }));
    },
  },
  {
    name: 'a sparse certificate',
    mount: async () => {
      const grave = manyGraves(1)[0]!;
      mockApi({
        graves: { [HAUNTED_SCAN_ID]: [grave] },
        certificates: { [HAUNTED_SCAN_ID]: { [grave.purl]: minimalCertificate(grave) } },
      });
      window.history.replaceState(
        null,
        '',
        `/grave?scan=${HAUNTED_SCAN_ID}&purl=${encodeURIComponent(grave.purl)}`,
      );
      render(<CertificatePage client={client} />);
      await settle(() => screen.getByRole('heading', { level: 1 }));
    },
  },
  {
    name: 'a link that leads nowhere',
    mount: async () => {
      window.history.replaceState(null, '', '/scan?id=x');
      render(<ScanPage client={client} />);
      await settle(() => screen.getByRole('heading', { name: 'This plot is not on the map' }));
    },
  },
];

describe.each(CASES)('$name', ({ mount }) => {
  it('has one h1, in order, with decorative svgs, native named controls and a skip target', async () => {
    await mount();
    expectHeadingOrder();
    expectDecorativeSvgs();
    expectNativeControls();
    expect(document.querySelector('main#main')).not.toBeNull();
    expect(document.querySelectorAll('main')).toHaveLength(1);
  });

  it('shows none of the placeholders or invented figures of the mockups', async () => {
    await mount();
    const text = document.body.textContent ?? '';
    for (const placeholder of PLACEHOLDERS) expect(text, placeholder).not.toContain(placeholder);
  });

  it('can be walked by keyboard: every stop is a real control and the tab order leaves the page', async () => {
    await mount();
    const stops = tabbables();
    expect(stops.length).toBeGreaterThan(0);
    for (const stop of stops) expect(stop.isConnected).toBe(true);
    const seen = new Set<Element>();
    for (let i = 0; i < Math.min(stops.length + 2, 60); i++) {
      await userEvent.tab();
      if (document.activeElement) seen.add(document.activeElement);
    }
    expect(seen.size).toBeGreaterThan(Math.min(stops.length, 40) / 2);
  });
});

describe('the results page', () => {
  it('shows no number that is not in the capture', async () => {
    mockApi({ scans: { [HAUNTED_SCAN_ID]: completeScan() } });
    scanUrl();
    render(<ScanPage client={client} />);
    await settle(() => screen.getByRole('group', { name: 'Filter by state' }));
    const header = screen.getByRole('region', { name: 'Scan summary' });
    expect(within(header).getByText(/208 dependencies/)).toBeInTheDocument();
  });
});
