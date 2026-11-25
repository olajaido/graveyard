import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createClient } from '@/lib/api/client';
import { VIEW_STORAGE_KEY } from '@/lib/hooks/use-view-state';
import { expectNoViolations } from '@/lib/test/axe';
import { mockApi } from '@/mocks/node';
import {
  emptyScan,
  manyGraves,
  partialScan,
  preBScan,
  withoutVia,
} from '@/mocks/fixtures/builders';
import { hauntedGraves, hauntedScan, HAUNTED_SCAN_ID } from '@/mocks/fixtures/haunted-house';
import { ResultsPage } from './results-page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const client = createClient({ baseUrl: 'https://api.test' });
const at = (search = '') =>
  window.history.replaceState(null, '', `/scan?id=${HAUNTED_SCAN_ID}${search}`);

beforeEach(() => {
  window.localStorage.clear();
  at();
});

async function results(scan = hauntedScan) {
  render(<ResultsPage scan={scan} client={client} />);
  await screen.findByRole('heading', { level: 1, name: scan.source.repo });
  await screen.findByRole('group', { name: /Filter by state/ });
}

const plotOf = (name: string) => screen.getByRole('region', { name });

describe('the scene', () => {
  it('draws a plot per service of the scan, with its stones and its subtitle', async () => {
    mockApi();
    await results();
    const root = plotOf('The root plot');
    const worker = plotOf('The worker plot');
    expect(within(root).getByText('service "." · npm · package-lock.json')).toBeInTheDocument();
    expect(
      within(worker).getByText('service "services/worker" · PyPI · requirements.txt'),
    ).toBeInTheDocument();
    expect(within(root).getAllByRole('link', { name: /priority \d+ of 137/ })).toHaveLength(24);
    expect(within(worker).getAllByRole('link')).toHaveLength(4);
  });

  it('caps the root plot at 24 stones, says what the other 109 are and links them to the table, filtered by service', async () => {
    mockApi();
    await results();
    const more = within(plotOf('The root plot')).getByRole('link', {
      name: /^see them in Lights on/,
    });
    expect(more).toHaveAttribute('href', `/scan?id=${HAUNTED_SCAN_ID}&view=table&service=.`);
    expect(more.parentElement).toHaveTextContent(
      'Also in this plot: 80 ailing and 29 resting, mostly brought in by other packages — see them in Lights on',
    );
    expect(within(plotOf('The worker plot')).queryByText(/Also in this plot/)).toBeNull();
  });

  it('names a stone like "lodash.template 3.6.2, Dead and cursed, priority 1 of 137"', async () => {
    mockApi();
    await results();
    const stone = screen.getByRole('link', {
      name: /^lodash\.template 3\.6\.2, Dead and cursed, priority 1 of 137$/,
    });
    expect(stone).toHaveAttribute('href', expect.stringContaining('/grave?scan='));
    expect(stone).toHaveTextContent('3.6.2 · via gulp-util');
  });

  it('writes the summary from the counts and never calls cursed a subset of dead', async () => {
    mockApi();
    await results();
    expect(
      screen.getByText('208 dependencies dug up across 2 plots. 17 dead, 2 cursed, 84 ailing.'),
    ).toBeInTheDocument();
    expect(screen.getByText('The living: 76 · Resting: 31')).toBeInTheDocument();
    expect(screen.getByText(/Exhumation complete · 23 Nov 2026/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/of those are cursed/);
  });

  it('lists the five graves to dig first as toe tags with their relation', async () => {
    mockApi();
    await results();
    const section = screen.getByRole('region', { name: 'Dig these first' });
    const tags = within(section).getAllByRole('link');
    expect(tags).toHaveLength(5);
    expect(tags[0]).toHaveTextContent('lodash.template@3.6.2');
    expect(tags[0]).toHaveTextContent('dead · cursed · via gulp-util');
    expect(tags[1]).toHaveTextContent('request@2.88.2');
  });

  it('puts the focus on the h1 and announces the completion', async () => {
    mockApi();
    await results();
    expect(screen.getByRole('heading', { level: 1 })).toHaveFocus();
    expect(screen.getByRole('status')).toHaveTextContent('Exhumation complete');
  });

  it('says the legend: size is relative to this scan', async () => {
    mockApi();
    await results();
    expect(
      screen.getByText(/Taller stones need you sooner, relative to this scan/),
    ).toBeInTheDocument();
  });
});

describe('roving tabindex in a plot', () => {
  it('has one tab stop per plot, and the arrow keys, Home and End move between the stones', async () => {
    mockApi();
    await results();
    const worker = within(plotOf('The worker plot')).getAllByRole('link');
    expect(worker.filter((a) => a.getAttribute('tabindex') === '0')).toHaveLength(1);
    expect(worker[0]).toHaveAttribute('tabindex', '0');
    worker[0]!.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(worker[1]).toHaveFocus();
    expect(worker[1]).toHaveAttribute('tabindex', '0');
    expect(worker[0]).toHaveAttribute('tabindex', '-1');
    await userEvent.keyboard('{End}');
    expect(worker[3]).toHaveFocus();
    await userEvent.keyboard('{ArrowRight}');
    expect(worker[3]).toHaveFocus();
    await userEvent.keyboard('{Home}');
    expect(worker[0]).toHaveFocus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(worker[0]).toHaveFocus();
  });

  it('Tab enters a plot once and leaves it', async () => {
    mockApi();
    await results();
    const root = within(plotOf('The root plot')).getAllByRole('link');
    root[0]!.focus();
    await userEvent.tab();
    expect(root[1]).not.toHaveFocus();
  });
});

describe('the chips and the view', () => {
  it('filters the scene with a pressed chip, and a plot with no match says so', async () => {
    mockApi();
    await results();
    const cursed = screen.getByRole('button', { name: 'Cursed, 2' });
    await userEvent.click(cursed);
    expect(cursed).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'All, 137' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(within(plotOf('The root plot')).getAllByRole('link')).toHaveLength(2);
    expect(
      within(plotOf('The worker plot')).getByText('No graves in this plot match the filter.'),
    ).toBeInTheDocument();
    expect(window.location.search).toContain('state=cursed');
    await userEvent.click(cursed);
    expect(screen.getByRole('button', { name: 'All, 137' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(window.location.search).not.toContain('state=');
  });

  it('shows the counts from the API on the chips', async () => {
    mockApi();
    await results();
    for (const [name, n] of [
      ['Dead', 17],
      ['Cursed', 2],
      ['Ailing', 84],
      ['Resting', 31],
      ['Wounded', 5],
    ] as const) {
      expect(screen.getByRole('button', { name: `${name}, ${n}` })).toBeInTheDocument();
    }
  });

  it('switches to Lights on, writes the URL and remembers the choice in this browser', async () => {
    mockApi();
    await results();
    await userEvent.click(screen.getByRole('button', { name: 'Lights on' }));
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(window.location.search).toContain('view=table');
    expect(window.localStorage.getItem(VIEW_STORAGE_KEY)).toBe('table');
    expect(screen.getByRole('button', { name: 'Lights on' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Graveyard' }));
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('opens in the remembered view when the URL has none, and the URL wins when it has one', async () => {
    mockApi();
    window.localStorage.setItem(VIEW_STORAGE_KEY, 'table');
    await results();
    expect(screen.getByRole('table')).toBeInTheDocument();
    at('&view=scene');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(screen.queryByRole('table')).toBeNull());
  });

  it('filters the table by the service of the "more in Lights on" link', async () => {
    mockApi();
    at('&view=table&service=services%2Fworker');
    await results();
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(1 + 4);
    expect(screen.getByRole('combobox', { name: 'Service' })).toHaveValue('services/worker');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Service' }), '');
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(1 + 137);
  });
});

describe('other scans', () => {
  it('shows the empty state when there are no graves', async () => {
    mockApi({ scans: { [HAUNTED_SCAN_ID]: emptyScan() }, graves: { [HAUNTED_SCAN_ID]: [] } });
    render(<ResultsPage scan={emptyScan()} client={client} />);
    expect(
      await screen.findByRole('heading', { name: 'No graves here. Your dependencies live.' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Filter by state' })).toBeNull();
  });

  it('shows the fog banner for a partial scan and names the packages that could not be examined', async () => {
    mockApi();
    await results(partialScan());
    expect(screen.getByRole('note')).toHaveTextContent(
      '7 packages could not be examined, so this picture is partial.',
    );
  });

  it('says nothing about unexamined packages for a complete scan', async () => {
    mockApi();
    await results();
    expect(screen.queryByRole('note')).toBeNull();
  });

  it('renders a scan from before group B: plots from the graves, no manifests, no via', async () => {
    mockApi({
      scans: { [HAUNTED_SCAN_ID]: preBScan() },
      graves: { [HAUNTED_SCAN_ID]: withoutVia(hauntedGraves.items) },
    });
    await results(preBScan());
    expect(within(plotOf('The root plot')).getByText('service "." · npm')).toBeInTheDocument();
    const stone = screen.getByRole('link', { name: /^lodash\.template 3\.6\.2/ });
    expect(stone).not.toHaveTextContent('via');
    expect(screen.getAllByRole('link', { name: /priority/ }).length).toBeGreaterThan(0);
  });

  it('shows a clean service as a plot with nothing buried', async () => {
    const services = [
      ...hauntedScan.services!,
      {
        id: 'services/clean',
        manifests: [{ ecosystem: 'pypi' as const, path: 'services/clean/uv.lock' }],
      },
    ];
    mockApi();
    await results({ ...hauntedScan, services });
    expect(
      within(plotOf('The clean plot')).getByText('Nothing buried here. This plot is clean.'),
    ).toBeInTheDocument();
  });

  it('reports an API failure and offers a retry', async () => {
    mockApi({ networkError: (_m, path) => path.includes('/graves') });
    render(<ResultsPage scan={hauntedScan} client={client} />);
    expect(
      await screen.findByRole('heading', { name: 'The path is out of reach' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('handles many graves: the cap keeps the scene small', async () => {
    mockApi({
      scans: { [HAUNTED_SCAN_ID]: hauntedScan },
      graves: { [HAUNTED_SCAN_ID]: manyGraves(450) },
    });
    await results();
    expect(within(plotOf('The root plot')).getAllByRole('link', { name: /priority/ })).toHaveLength(
      24,
    );
    expect(
      within(plotOf('The root plot')).getByRole('link', { name: /^see them in Lights on/ }),
    ).toBeInTheDocument();
    expect(within(plotOf('The root plot')).getByText(/^Also in this plot: /)).toBeInTheDocument();
  });
});

describe('the summary header', () => {
  it('keeps the art behind the text, and the moon and stars to the right of the text column', async () => {
    mockApi();
    await results();
    const summary = screen.getByRole('region', { name: 'Scan summary' });
    expect(summary).toHaveClass('isolate');
    const art = summary.firstElementChild as HTMLElement;
    const text = summary.lastElementChild as HTMLElement;
    expect(art).toHaveAttribute('aria-hidden', 'true');
    expect(art).toHaveClass('z-0', 'pointer-events-none');
    expect(text).toHaveClass('z-10', 'relative');
    expect(within(text).getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(text.querySelector('svg')?.closest('a')).not.toBeNull(); // only the toe-tag icons draw in the text layer
    // Stars: only in the right-hand box, which starts after the 620px text column and is hidden on narrow screens.
    const box = within(art).getByTestId('sky-objects');
    expect(box).toHaveClass('hidden', 'md:block');
    expect(box.style.left).toBe('max(680px, 52%)');
    expect(art.querySelectorAll('circle')).toHaveLength(box.querySelectorAll('circle').length);
  });
});

describe('accessibility', () => {
  it('has no axe violations in the scene or in the table', async () => {
    mockApi();
    const { container } = render(
      <main>
        <ResultsPage scan={hauntedScan} client={client} />
      </main>,
    );
    await screen.findByRole('group', { name: /Filter by state/ });
    await expectNoViolations(container);
    await userEvent.click(screen.getByRole('button', { name: 'Lights on' }));
    await screen.findByRole('table');
    await expectNoViolations(container);
  });
});
