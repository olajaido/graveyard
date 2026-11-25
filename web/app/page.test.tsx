import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import evidence from '@/content/evidence.generated.json';
import scan from '@/content/haunted-house/scan.json';
import { expectNoViolations } from '@/lib/test/axe';
import Home from './page';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

describe('the landing page', () => {
  it('has the sections of the mockup in order, one h1 and the nav', () => {
    render(<Home />);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual([
      'The autopsy, in four acts',
      'Six states of being',
      "We don't guess at death",
    ]);
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(
      within(nav)
        .getAllByRole('link')
        .map((a) => a.getAttribute('href')),
    ).toEqual(['#how', '#states', '#evidence', 'https://github.com/olajaido/graveyard']);
    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  it('shows the example from the committed capture, not typed figures', () => {
    render(<Home />);
    const strip = screen.getByRole('region', { name: 'Example result' });
    const text = strip.textContent ?? '';
    for (const n of [scan.counts.total, scan.counts.dead, scan.counts.cursed, scan.counts.ailing]) {
      expect(text).toContain(String(n));
    }
    expect(text).toContain('olajaido/haunted-house, exhumed in 31 seconds');
    expect(text).toContain('A real scan of 23 Nov 2026.');
  });

  it('writes the six states from the PRD definitions, for model v2', () => {
    render(<Home />);
    const states = screen.getByRole('region', { name: 'Six states of being' });
    const items = within(states).getAllByRole('listitem');
    expect(items).toHaveLength(6);
    const by = (name: string) => items.find((li) => li.textContent?.startsWith(name))!.textContent!;
    expect(by('Dead')).toContain('(abandoned)');
    expect(by('Dead')).toContain('Declared dead on evidence');
    expect(by('Cursed')).toContain('(unfixable vulnerability)');
    expect(by('Cursed')).toContain('no fix, on any package');
    expect(by('Wounded')).toContain('(fixable vulnerability)');
    expect(by('Wounded')).toContain('on any package');
    const whole = states.textContent ?? '';
    expect(whole).not.toMatch(/dead and carrying|Still alive|score/i);
  });

  it('shows the held-out result and says the verdict was inconclusive when it was', () => {
    render(<Home />);
    const section = screen.getByRole('region', { name: "We don't guess at death" });
    expect(section).toHaveTextContent(
      `${evidence.deadPrecision.num}/${evidence.deadPrecision.den}`,
    );
    expect(section).toHaveTextContent('95% interval 0.72 – 1.00');
    if (!evidence.verdictPassed)
      expect(section).toHaveTextContent('the formal verdict was inconclusive');
  });

  it('offers no SBOM upload and no instant demo', () => {
    render(<Home />);
    expect(document.body.textContent).not.toMatch(/upload|sbom|demo/i);
  });

  it('has no axe violations', async () => {
    const { container } = render(<Home />);
    await expectNoViolations(container, { wholePage: true });
  });
});
