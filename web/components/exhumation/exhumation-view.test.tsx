import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { expectNoViolations } from '@/lib/test/axe';
import { runningScan } from '@/mocks/fixtures/builders';
import { formatElapsed } from './elapsed';
import { ExhumationView } from './exhumation-view';
import { captions } from './lantern-path';

const lanterns = () => within(screen.getByRole('list')).getAllByRole('listitem');
const word = (li: HTMLElement) => li.lastElementChild?.textContent;

describe('ExhumationView', () => {
  it('names the repository in the h1 and takes focus there', () => {
    render(<ExhumationView scan={runningScan('FETCH')} />);
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveTextContent('olajaido/haunted-house');
    expect(h1).toHaveFocus();
  });

  it.each([
    ['QUEUED', ['waiting', 'waiting', 'waiting', 'waiting', 'waiting', 'waiting']],
    ['VALIDATE', ['working', 'waiting', 'waiting', 'waiting', 'waiting', 'waiting']],
    ['FETCH', ['done', 'working', 'waiting', 'waiting', 'waiting', 'waiting']],
    ['SBOM', ['done', 'done', 'working', 'waiting', 'waiting', 'waiting']],
    ['GRAPH', ['done', 'done', 'done', 'working', 'waiting', 'waiting']],
    ['AUTOPSY', ['done', 'done', 'done', 'done', 'working', 'waiting']],
    ['CLASSIFY', ['done', 'done', 'done', 'done', 'done', 'working']],
  ] as const)('lights the lanterns of stage %s, in words', (stage, words) => {
    render(<ExhumationView scan={runningScan(stage, { examined: 3, total: 9 })} />);
    expect(lanterns().map(word)).toEqual(words);
    const current = lanterns().filter((li) => li.getAttribute('aria-current') === 'step');
    expect(current).toHaveLength(stage === 'QUEUED' ? 0 : 1);
  });

  it('says "N of M examined" from the API during the autopsy, and clamps it', () => {
    const { rerender } = render(
      <ExhumationView scan={runningScan('AUTOPSY', { examined: 142, total: 208 })} />,
    );
    expect(screen.getByText('142 of 208 examined')).toBeInTheDocument();
    rerender(<ExhumationView scan={runningScan('AUTOPSY', { examined: 300, total: 208 })} />);
    expect(screen.getByText('208 of 208 examined')).toBeInTheDocument();
  });

  it('moves the dig depth with the stage and the progress', () => {
    const depth = () => Number(screen.getByTestId('backfill').getAttribute('height'));
    const { rerender } = render(<ExhumationView scan={runningScan('VALIDATE')} />);
    const shallow = depth();
    rerender(<ExhumationView scan={runningScan('AUTOPSY', { examined: 0, total: 100 })} />);
    const mid = depth();
    rerender(<ExhumationView scan={runningScan('AUTOPSY', { examined: 100, total: 100 })} />);
    expect(shallow).toBeGreaterThan(mid);
    expect(mid).toBeGreaterThan(depth());
  });

  it('invents no numbers while the API gives none', () => {
    render(<ExhumationView scan={runningScan('GRAPH')} />);
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/\d+ of \d+/);
    expect(text).not.toMatch(/%/);
    expect(text).not.toMatch(/tally|toe tag|fresh/i);
  });

  it('counts the lockfiles and plots from the service list, and says nothing before it exists', () => {
    const { rerender } = render(<ExhumationView scan={runningScan('FETCH')} />);
    expect(screen.getByText('2 lockfiles dug up')).toBeInTheDocument();
    expect(screen.getByText(/2 plots found/)).toBeInTheDocument();
    rerender(<ExhumationView scan={runningScan('VALIDATE')} />);
    expect(screen.queryByText(/plots found/)).toBeNull();
    expect(screen.getByText('the lockfiles')).toBeInTheDocument();
  });

  it('renders a scan from before group B (no services, no progress)', () => {
    render(<ExhumationView scan={{ ...runningScan('AUTOPSY', null), services: null }} />);
    expect(screen.getByText('the bodies')).toBeInTheDocument();
  });

  it('announces the stage in a polite status region, and the examined count only when a tenth more is done', () => {
    const status = () => screen.getByRole('status');
    const { rerender } = render(
      <ExhumationView scan={runningScan('AUTOPSY', { examined: 1, total: 100 })} />,
    );
    expect(status()).toHaveTextContent('Examining the bodies: 1 of 100 examined');
    rerender(<ExhumationView scan={runningScan('AUTOPSY', { examined: 5, total: 100 })} />);
    expect(status()).toHaveTextContent('Examining the bodies: 1 of 100 examined');
    rerender(<ExhumationView scan={runningScan('AUTOPSY', { examined: 12, total: 100 })} />);
    expect(status()).toHaveTextContent('Examining the bodies: 12 of 100 examined');
    rerender(<ExhumationView scan={runningScan('CLASSIFY')} />);
    expect(status()).toHaveTextContent('Pronouncing');
  });

  it('keeps the clock out of the live region', () => {
    render(<ExhumationView scan={runningScan('FETCH')} />);
    expect(screen.getByRole('status')).not.toHaveTextContent(/second/);
    expect(screen.getByText(/Digging now/)).toHaveTextContent(/\d+ seconds?|\d+ min/);
  });

  it('has no axe violations in any stage', async () => {
    for (const stage of ['QUEUED', 'FETCH', 'AUTOPSY', 'CLASSIFY'] as const) {
      const { container, unmount } = render(
        <main>
          <ExhumationView scan={runningScan(stage, { examined: 4, total: 9 })} />
        </main>,
      );
      await expectNoViolations(container);
      unmount();
    }
  });
});

describe('formatElapsed', () => {
  it.each([
    [0, '0 seconds'],
    [1, '1 second'],
    [41, '41 seconds'],
    [60, '1 min 0 s'],
    [125, '2 min 5 s'],
  ])('%i', (s, text) => expect(formatElapsed(s)).toBe(text));
});

describe('captions', () => {
  it('are descriptions, or numbers of the API', () => {
    expect(captions(null, null)).toEqual([
      'public repository',
      'the lockfiles',
      'package inventory',
      'who brought whom',
      'the bodies',
      'final states',
    ]);
    expect(
      captions([{ id: '.', manifests: [{ ecosystem: 'npm', path: 'a' }] }], {
        examined: 1,
        total: 2,
      })[1],
    ).toBe('1 lockfile dug up');
  });
});
