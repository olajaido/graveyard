import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { GraveSummary } from '@/lib/api/types';
import { sortGraves } from '@/lib/model/filter-sort';
import type { SortDir, SortKey } from '@/lib/model/route';
import { makeGrave } from '@/lib/model/test-data';
import { expectNoViolations } from '@/lib/test/axe';
import { manyGraves } from '@/mocks/fixtures/builders';
import { hauntedGraves, HAUNTED_SCAN_ID } from '@/mocks/fixtures/haunted-house';
import { LightsOnTable, formatPriority } from './lights-on-table';
import { OVERSCAN, ROW_HEIGHT, WINDOW_THRESHOLD } from './use-window-rows';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

function Harness({
  graves,
  initial = ['priority', 'desc'] as [SortKey, SortDir],
}: {
  graves: GraveSummary[];
  initial?: [SortKey, SortDir];
}) {
  const [[sort, dir], setSort] = useState(initial);
  return (
    <LightsOnTable
      scanId={HAUNTED_SCAN_ID}
      graves={sortGraves(graves, sort, dir)}
      sort={sort}
      dir={dir}
      onSort={(s, d) => setSort([s, d])}
    />
  );
}

const rowNames = () =>
  within(screen.getByRole('table'))
    .getAllByRole('row')
    .slice(1)
    .map((r) => within(r).getAllByRole('rowheader')[0]?.textContent);

describe('the table', () => {
  it('is a real table on parchment with a caption, a named focusable region and the seven columns', () => {
    render(<Harness graves={hauntedGraves.items} />);
    const region = screen.getByRole('region', { name: 'Register of graves' });
    expect(region).toHaveAttribute('tabindex', '0');
    expect(region.className).toContain('surface-paper');
    expect(
      screen.getByRole('table', { name: 'The register, with the lights on' }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole('columnheader').map((h) => h.textContent?.replace(/[↑↓]/, '')),
    ).toEqual(['Package', 'State', 'Priority', 'Cause', 'Relationship', 'Scope', 'Service']);
    expect(screen.getAllByRole('row')).toHaveLength(1 + 137);
  });

  it('prints each row from the facts of the list: package link, state pill, priority, cause, relationship, scope, service', () => {
    render(<Harness graves={hauntedGraves.items} />);
    const row = screen.getAllByRole('row')[1]!;
    expect(within(row).getByRole('link', { name: 'lodash.template@3.6.2' })).toHaveAttribute(
      'href',
      `/grave?scan=${HAUNTED_SCAN_ID}&purl=pkg%3Anpm%2Flodash.template%403.6.2`,
    );
    const cells = within(row)
      .getAllByRole('cell')
      .map((c) => c.textContent);
    expect(cells).toEqual([
      'dead · cursed',
      '108.0',
      'Declared dead by its source; Known vulnerability, no fix available',
      'via gulp-util',
      'runtime',
      '.',
    ]);
  });

  it('writes "not recorded" for a missing priority and a dash for no cause', () => {
    render(<Harness graves={[makeGrave({ state: 'alive', priority: null })]} />);
    expect(screen.getByText('not recorded')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(formatPriority(null)).toBe('not recorded');
    expect(formatPriority(86.4)).toBe('86.4');
  });

  it('starts sorted by priority, highest first, and says so with aria-sort', () => {
    render(<Harness graves={hauntedGraves.items} />);
    expect(screen.getByRole('columnheader', { name: /Priority/ })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    expect(screen.getByRole('columnheader', { name: /Package/ })).toHaveAttribute(
      'aria-sort',
      'none',
    );
    expect(rowNames()[0]).toBe('lodash.template@3.6.2');
  });

  it.each([
    ['Package', 'ascending', 'descending'],
    ['State', 'ascending', 'descending'],
    ['Priority', 'descending', 'ascending'],
  ])('sorts by %s and toggles the direction', async (column, first, second) => {
    render(
      <Harness
        graves={hauntedGraves.items}
        initial={['priority', column === 'Priority' ? 'asc' : 'desc']}
      />,
    );
    const header = () => screen.getByRole('columnheader', { name: new RegExp(column) });
    const button = within(header()).getByRole('button', { name: new RegExp(column) });
    await userEvent.click(button);
    expect(header()).toHaveAttribute('aria-sort', column === 'Priority' ? 'descending' : first);
    const before = rowNames();
    await userEvent.click(within(header()).getByRole('button'));
    expect(header()).toHaveAttribute('aria-sort', column === 'Priority' ? 'ascending' : second);
    expect(rowNames()).not.toEqual(before);
  });

  it('sorts by package name in number-aware order, ascending first', async () => {
    render(<Harness graves={hauntedGraves.items} />);
    await userEvent.click(screen.getByRole('button', { name: /Package/ }));
    const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });
    const names = rowNames().map((n) => n!.slice(0, n!.lastIndexOf('@')));
    for (let k = 1; k < names.length; k++) {
      expect(collator.compare(names[k - 1]!, names[k]!)).toBeLessThanOrEqual(0);
    }
  });

  it('sorts by state with cursed first, and keeps the order stable', async () => {
    render(<Harness graves={hauntedGraves.items} />);
    await userEvent.click(screen.getByRole('button', { name: /State/ }));
    expect(rowNames().slice(0, 2)).toEqual(['lodash.template@3.6.2', 'request@2.88.2']);
  });

  it('is operable by keyboard: Tab to a header, Enter to sort, Tab to a link', async () => {
    render(<Harness graves={hauntedGraves.items} />);
    screen.getByRole('region', { name: 'Register of graves' }).focus();
    await userEvent.tab();
    expect(screen.getByRole('button', { name: /Package/ })).toHaveFocus();
    await userEvent.keyboard('{Enter}');
    expect(screen.getByRole('columnheader', { name: /Package/ })).toHaveAttribute(
      'aria-sort',
      'ascending',
    );
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    expect(within(screen.getAllByRole('row')[1]!).getByRole('link')).toHaveFocus();
  });

  it('has no axe violations', async () => {
    const { container } = render(<Harness graves={hauntedGraves.items} />);
    await expectNoViolations(container);
  });
});

describe('windowing', () => {
  const body = () =>
    within(screen.getByRole('table'))
      .getAllByRole('row')
      .filter((r) => r.getAttribute('aria-hidden') !== 'true');

  it('renders every row at 500 rows', () => {
    render(<Harness graves={manyGraves(WINDOW_THRESHOLD)} />);
    expect(body()).toHaveLength(1 + 500);
    expect(screen.getByRole('table')).not.toHaveAttribute('aria-rowcount');
  });

  it('renders a window at 501 rows with the row count and row indexes', () => {
    render(<Harness graves={manyGraves(WINDOW_THRESHOLD + 1)} />);
    const table = screen.getByRole('table');
    expect(table).toHaveAttribute('aria-rowcount', '502');
    const rows = body();
    expect(rows.length).toBeLessThan(60);
    expect(rows[0]).toHaveAttribute('aria-rowindex', '1');
    expect(rows[1]).toHaveAttribute('aria-rowindex', '2');
    const spacer = table.querySelector('tbody tr[aria-hidden="true"]') as HTMLElement;
    expect(spacer.style.height).toBe(`${(501 - (rows.length - 1)) * ROW_HEIGHT}px`);
  });

  it('moves the window with the scroll position and keeps the indexes right', () => {
    render(<Harness graves={manyGraves(600)} />);
    const region = screen.getByRole('region', { name: 'Register of graves' });
    Object.defineProperty(region, 'scrollTop', { value: 300 * ROW_HEIGHT, configurable: true });
    Object.defineProperty(region, 'clientHeight', { value: 700, configurable: true });
    fireEvent.scroll(region);
    const rows = body();
    const indexes = rows.slice(1).map((r) => Number(r.getAttribute('aria-rowindex')));
    expect(indexes[0]).toBe(300 - OVERSCAN + 2);
    expect(indexes.at(-1)).toBeGreaterThan(300 + 14);
    expect(indexes).toEqual([...indexes].sort((a, b) => a - b));
    const top = screen
      .getByRole('table')
      .querySelector('tbody tr[aria-hidden="true"]') as HTMLElement;
    expect(top.style.height).toBe(`${(300 - OVERSCAN) * ROW_HEIGHT}px`);
  });

  it('has no axe violations when windowed', async () => {
    const { container } = render(<Harness graves={manyGraves(700)} />);
    await expectNoViolations(container);
  });
});
