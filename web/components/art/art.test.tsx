import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BrandMark } from './brand-mark';
import { FenceStrip } from './fence-strip';
import { Grave, type GraveType } from './grave';
import { GraveIcon } from './grave-icon';
import { GraveyardSky, SkyObjects } from './graveyard-sky';
import { Lantern } from './lantern';
import { NightScene } from './night-scene';
import { OpenGraveScene } from './open-grave-scene';
import { PlotBackdrop } from './plot-backdrop';
import { StepArt } from './step-art';
import { ToeTagIcon } from './toe-tag-icon';
import { WaxSeal } from './wax-seal';

const TYPES: GraveType[] = ['cursed', 'dead', 'ailing', 'resting', 'wounded', 'alive'];

const everything = [
  <BrandMark key="b" />,
  <FenceStrip key="f" />,
  <GraveyardSky key="s" />,
  <SkyObjects key="so" />,
  <NightScene key="n" />,
  <OpenGraveScene key="o" depth={0.5} />,
  <PlotBackdrop key="p" />,
  <ToeTagIcon key="t" color="#8A2B1F" />,
  <WaxSeal key="w" word="DECEASED" date="22·XI·2026" />,
  ...TYPES.map((t) => <Grave key={`g${t}`} type={t} width={100} />),
  ...TYPES.map((t) => <GraveIcon key={`i${t}`} type={t} />),
  ...(['lit', 'working', 'unlit'] as const).map((s) => <Lantern key={`l${s}`} state={s} />),
  ...(['exhume', 'identify', 'trace', 'pronounce'] as const).map((s) => (
    <StepArt key={`a${s}`} step={s} />
  )),
];

/** The classes that drive a CSS animation of `opacity` (globals.css): gyglow, gytw, gyflame, gydirt. */
const OPACITY_ANIMATED = ['gy-glow', 'gy-star', 'gy-flame', 'gy-dirt', 'gy-dirt2'];

describe('art components', () => {
  it('no element that animates its opacity has an opacity of its own (the animation would replace it)', () => {
    const sites: string[] = [];
    for (const element of everything) {
      const { container, unmount } = render(element);
      for (const cls of OPACITY_ANIMATED)
        for (const el of container.querySelectorAll(`.${cls}`)) {
          if (el.hasAttribute('opacity') || el.hasAttribute('fill-opacity'))
            sites.push(`${String(element.key)}: .${cls} <${el.tagName}>`);
        }
      unmount();
    }
    expect(sites).toEqual([]);
  });
  it('the cursed glow is a faint ellipse inside the animated group', () => {
    const { container } = render(<Grave type="cursed" width={100} />);
    const glow = container.querySelector('g.gy-glow > ellipse');
    expect(glow).not.toBeNull();
    const opacity = Number(glow!.getAttribute('opacity'));
    // The group animates between 0.55 and 1, so the glow stays between about 0.10 and 0.18.
    expect(opacity * 0.55).toBeGreaterThanOrEqual(0.09);
    expect(opacity).toBeLessThanOrEqual(0.2);
  });
  it('the hills of the results header have no stars, the moon and stars are their own layer', () => {
    const sky = render(<GraveyardSky />).container;
    expect(sky.querySelectorAll('circle')).toHaveLength(0);
    const objects = render(<SkyObjects />).container;
    expect(objects.querySelectorAll('circle').length).toBeGreaterThan(8);
  });
  it.each(everything.map((el) => [String(el.key), el] as const))(
    '%s is decorative: aria-hidden and not focusable',
    (_key, element) => {
      const { container } = render(element);
      const svgs = container.querySelectorAll('svg');
      expect(svgs).toHaveLength(1);
      expect(svgs[0]).toHaveAttribute('aria-hidden', 'true');
      expect(svgs[0]).toHaveAttribute('focusable', 'false');
      expect(svgs[0]?.querySelector('title')).toBeNull();
    },
  );

  it('two copies of a patterned scene get different pattern ids', () => {
    const { container } = render(
      <>
        <PlotBackdrop />
        <PlotBackdrop />
        <NightScene />
        <NightScene />
        <FenceStrip />
        <FenceStrip />
      </>,
    );
    const ids = [...container.querySelectorAll('pattern')].map((p) => p.id);
    expect(ids).toHaveLength(6);
    expect(new Set(ids).size).toBe(6);
    for (const id of ids) expect(id).toMatch(/^[A-Za-z][A-Za-z0-9_-]*$/);
    // every fill that points at a pattern points at an existing one
    const refs = [...container.querySelectorAll('[fill^="url(#"]')].map((e) =>
      e.getAttribute('fill')!.slice(5, -1),
    );
    expect(refs.every((r) => ids.includes(r))).toBe(true);
  });

  it('the dig depth moves the backfill and clamps', () => {
    const y = (depth: number) => {
      const { getByTestId, unmount } = render(<OpenGraveScene depth={depth} />);
      const rect = getByTestId('backfill');
      const out = [Number(rect.getAttribute('y')), Number(rect.getAttribute('height'))];
      unmount();
      return out;
    };
    expect(y(0)).toEqual([262, 140]); // the pit is covered
    expect(y(0.5)).toEqual([332, 70]);
    expect(y(1)).toEqual([402, 0]); // the pit is open
    expect(y(2)).toEqual(y(1));
    expect(y(-1)).toEqual(y(0));
    expect(y(Number.NaN)).toEqual(y(0));
  });

  it('the seal shows the word and the date', () => {
    const { container } = render(<WaxSeal word="CURSED" date="22·XI·2026" tone="cursed" />);
    expect(container.textContent).toBe('CURSED22·XI·2026');
  });
});
