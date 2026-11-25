import { render } from '@testing-library/react';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import Home from '@/app/page';
import { ViewToggle } from '@/components/graveyard/view-toggle';
import { ExhumationView } from '@/components/exhumation/exhumation-view';
import { runningScan } from '@/mocks/fixtures/builders';
import { BrandMark } from './brand-mark';
import { FenceStrip } from './fence-strip';
import { Grave, type GraveType } from './grave';
import { GraveIcon } from './grave-icon';
import { GraveyardSky } from './graveyard-sky';
import { Lantern } from './lantern';
import { OpenGraveScene } from './open-grave-scene';
import { PlotBackdrop } from './plot-backdrop';
import { ToeTagIcon } from './toe-tag-icon';
import { WaxSeal } from './wax-seal';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const MOCKUPS = resolve(process.cwd(), '../design/mockups');
const TYPES: GraveType[] = ['cursed', 'dead', 'ailing', 'resting', 'wounded', 'alive'];

/** Path data the mockups draw with, but this UI deliberately does not: the "Perform the rites" button icon (D8). */
const NOT_PORTED = new Set(['M6 3v12', 'M18 9a9 9 0 0 1-9 9']);

function mockupShapes(): { file: string; shape: string }[] {
  const out: { file: string; shape: string }[] = [];
  for (const file of readdirSync(MOCKUPS).filter((f) => f.endsWith('.dc.html'))) {
    const html = readFileSync(resolve(MOCKUPS, file), 'utf8');
    for (const match of html.matchAll(/\s(?:d|points)="([^"{}]+)"/g)) {
      const shape = match[1]!.trim();
      if (shape.length > 6) out.push({ file, shape });
    }
  }
  return out;
}

describe('the art is the mockups, not a redraw', () => {
  it('has every static path of the four mockups in a component, except the ones left out on purpose', () => {
    const rendered = [
      render(<Home />).container.innerHTML,
      render(<ExhumationView scan={runningScan('AUTOPSY', { examined: 1, total: 2 })} />).container
        .innerHTML,
      render(<ViewToggle value="scene" onChange={() => undefined} />).container.innerHTML,
      render(<BrandMark />).container.innerHTML,
      render(<FenceStrip />).container.innerHTML,
      render(<GraveyardSky />).container.innerHTML,
      render(<PlotBackdrop />).container.innerHTML,
      render(<OpenGraveScene depth={0.5} />).container.innerHTML,
      render(<ToeTagIcon color="#000" />).container.innerHTML,
      render(<WaxSeal word="DECEASED" date="22·XI·2026" />).container.innerHTML,
      ...TYPES.map((t) => render(<Grave type={t} width={100} />).container.innerHTML),
      ...TYPES.map((t) => render(<GraveIcon type={t} />).container.innerHTML),
      ...(['lit', 'working', 'unlit'] as const).map(
        (s) => render(<Lantern state={s} />).container.innerHTML,
      ),
      // The back chevron of the certificate header is plain markup in the page component.
      readFileSync(resolve(process.cwd(), 'components/certificate/certificate-page.tsx'), 'utf8'),
    ].join('\n');
    const shapes = mockupShapes();
    expect(shapes.length).toBeGreaterThan(100);
    const missing = shapes.filter(
      ({ shape }) => !NOT_PORTED.has(shape) && !rendered.includes(shape),
    );
    expect(missing).toEqual([]);
  });

  it('left out only the rites icon', () => {
    const shapes = mockupShapes().map((s) => s.shape);
    for (const shape of NOT_PORTED) expect(shapes).toContain(shape);
  });
});
