import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createClient } from '@/lib/api/client';
import { ERROR_COPY } from '@/lib/api/errors';
import type { ErrorCode } from '@/lib/api/types';
import { expectNoViolations } from '@/lib/test/axe';
import { completeScan, failedScan, runningScan } from '@/mocks/fixtures/builders';
import { HAUNTED_SCAN_ID } from '@/mocks/fixtures/haunted-house';
import { server, mockApi } from '@/mocks/node';
import { http, HttpResponse } from 'msw';
import { ScanPage } from './scan-page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const client = createClient({ baseUrl: 'https://api.test' });
const open = (search: string) => window.history.replaceState(null, '', `/scan${search}`);

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  window.localStorage.clear();
});
afterEach(() => {
  vi.useRealTimers();
});

const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

describe('ScanPage', () => {
  it.each(['', '?id=nope', '?scan=x', `?id=${HAUNTED_SCAN_ID}x`])(
    'shows the themed 404 for the link %j, without calling the API',
    async (search) => {
      const api = mockApi();
      open(search);
      render(<ScanPage client={client} />);
      expect(
        await screen.findByRole('heading', { level: 1, name: 'This plot is not on the map' }),
      ).toBeInTheDocument();
      expect(screen.getByText(/30 days/)).toBeInTheDocument();
      expect(api.calls).toEqual([]);
      await waitFor(() => expect(document.title).toBe('Not found · Graveyard'));
    },
  );

  it('shows the 404 for a scan the API does not know', async () => {
    mockApi({ scans: {} });
    open(`?id=${HAUNTED_SCAN_ID}`);
    render(<ScanPage client={client} />);
    expect(
      await screen.findByRole('heading', { level: 1, name: 'This plot is not on the map' }),
    ).toBeInTheDocument();
  });

  it('follows a scan through its stages and swaps to the results at the same URL', async () => {
    mockApi({
      scans: {
        [HAUNTED_SCAN_ID]: [
          runningScan('FETCH'),
          runningScan('AUTOPSY', { examined: 100, total: 208 }),
          completeScan(),
        ],
      },
    });
    open(`?id=${HAUNTED_SCAN_ID}`);
    render(<ScanPage client={client} />);
    expect(
      await screen.findByRole('heading', { level: 1, name: 'olajaido/haunted-house' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Digging now/)).toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe('Exhuming olajaido/haunted-house · Graveyard'));
    expect(screen.getByRole('link', { name: 'Graveyard' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy link to this scan' })).toBeInTheDocument();

    await advance(1600);
    expect(await screen.findByText('100 of 208 examined')).toBeInTheDocument();

    await advance(2300);
    expect(await screen.findByText(/Exhumation complete · 23 Nov 2026/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveFocus());
    expect(screen.getAllByRole('status').map((r) => r.textContent)).toContain(
      'Exhumation complete',
    );
    expect(window.location.pathname).toBe('/scan');
    expect(screen.getByRole('button', { name: 'Share results' })).toBeInTheDocument();
    const another = screen.getByRole('link', { name: 'Exhume another' });
    expect(another).toHaveAttribute('href', '/');
    // Its name is text people can see, drawn in the dark text colour of a bone button (the cascade is in e2e).
    expect(another.textContent).toBe('Exhume another');
    expect(another.querySelector('.sr-only')).toBeNull();
    expect(another).toHaveClass('bg-bone', 'text-on-bone');
    await waitFor(() => expect(document.title).toBe('olajaido/haunted-house · Graveyard'));
    expect(screen.queryByText(/Digging now/)).toBeNull();
  });

  it('goes straight to the results for a finished scan', async () => {
    const api = mockApi();
    open(`?id=${HAUNTED_SCAN_ID}`);
    render(<ScanPage client={client} />);
    expect(await screen.findByText(/Exhumation complete · 23 Nov 2026/)).toBeInTheDocument();
    expect(api.reads[HAUNTED_SCAN_ID]).toBe(1);
  });

  it.each(Object.keys(ERROR_COPY) as ErrorCode[])(
    'shows the themed message for a scan that failed with %s',
    async (code) => {
      mockApi({ scans: { [HAUNTED_SCAN_ID]: failedScan(code, 'FETCH', 'Server title') } });
      open(`?id=${HAUNTED_SCAN_ID}`);
      render(<ScanPage client={client} />);
      expect(
        await screen.findByRole('heading', { level: 1, name: ERROR_COPY[code].title }),
      ).toBeInTheDocument();
      expect(screen.getByText(ERROR_COPY[code].body)).toBeInTheDocument();
      expect(screen.getByText('olajaido/haunted-house')).toBeInTheDocument();
      expect(screen.queryByText(/Digging now/)).toBeNull();
    },
  );

  it('shows "Lost the trail" after five failed reads, and Retry picks it up again', async () => {
    let down = true;
    mockApi();
    server.use(
      http.get(/\/v1\/scans\/[^/]+$/, () =>
        down ? HttpResponse.error() : HttpResponse.json(completeScan()),
      ),
    );
    open(`?id=${HAUNTED_SCAN_ID}`);
    render(<ScanPage client={client} />);
    await advance(40_000);
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Lost the trail' }),
    ).toBeInTheDocument();
    down = false;
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText(/Exhumation complete · /)).toBeInTheDocument();
  });

  it('has no axe violations while running, when finished and when failed', async () => {
    for (const script of [[runningScan('GRAPH')], [completeScan()], [failedScan('NO_MANIFESTS')]]) {
      mockApi({ scans: { [HAUNTED_SCAN_ID]: script } });
      open(`?id=${HAUNTED_SCAN_ID}`);
      const { container, unmount } = render(<ScanPage client={client} />);
      await screen.findByRole('heading', { level: 1 });
      await advance(50);
      await expectNoViolations(container, { wholePage: true });
      unmount();
    }
  });
});
