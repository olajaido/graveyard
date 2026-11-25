import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

// The ids of the mock API of the test build (mocks/browser.ts): the haunted-house scan runs through every stage when it is
// read, the second one is already complete.
const RUNNING = '01M84GKAYX7D2JGJ1PYN5JGSS7-e066cd4c1ba726a8';
const DONE = '01M84GKAYX7D2JGJ1PYN5JGSS7-aaaaaaaaaaaaaaaa';
const UNKNOWN = '01M84GKAYX7D2JGJ1PYN5JGSS7-0000000000000000';
const SCOPED = 'pkg:npm/%40babel/core@7.0.0';
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'];

const grave = (scan: string, purl: string) =>
  `/grave?${new URLSearchParams({ scan, purl }).toString()}`;

/** axe with the full rule set, colour contrast included (it needs a real browser), on the page as it is now. */
async function settle(page: Page) {
  // Plots fade in; axe must not read a colour in the middle of that.
  await page.waitForFunction(() =>
    [...document.querySelectorAll('section[aria-labelledby]')].every(
      (el) => getComputedStyle(el).opacity === '1',
    ),
  );
}

async function axe(page: Page, label: string) {
  await settle(page);
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const found = results.violations.map(
    (v) =>
      `${v.id} (${v.nodes
        .map((n) => n.target.join(' '))
        .slice(0, 3)
        .join(' | ')})`,
  );
  expect(found, `axe on ${label}`).toEqual([]);
}

async function noSideScroll(page: Page, label: string) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow, `horizontal scroll on ${label}`).toBeLessThanOrEqual(0);
}

const animations = (page: Page) => page.evaluate(() => document.getAnimations().length);

test.beforeEach(async ({ page }) => {
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(`page error: ${e.message}`));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    // The browser logs the deliberate 404s (an unknown scan, a package not in the scan); nothing else may be logged.
    const url = m.location().url;
    const intended =
      url.endsWith(`/v1/scans/${UNKNOWN}`) ||
      url.endsWith('/graves/pkg%3Anpm%2Fnot-in-this-scan%401.0.0');
    if (m.text().includes('status of 404') && intended) return;
    problems.push(`console error: ${m.text()} @ ${m.location().url}`);
  });
  test.info().annotations.push({ type: 'problems', description: 'collected per test' });
  (page as Page & { problems?: string[] }).problems = problems;
});

test.afterEach(async ({ page }) => {
  expect((page as Page & { problems?: string[] }).problems ?? []).toEqual([]);
});

test('the full flow: landing, exhumation, graveyard, Lights on, certificate, back, 404', async ({
  page,
}) => {
  // Landing and the form
  await page.goto('/');
  await expect(
    page.getByRole('heading', { level: 1, name: /Every codebase has a graveyard/ }),
  ).toBeVisible();
  await axe(page, 'the landing page');
  await expect(page.getByLabel('Public GitHub repository')).toHaveValue('olajaido/haunted-house');
  await page.getByRole('button', { name: 'Exhume' }).click();

  // The exhumation: every stage, with moving progress
  await expect(page).toHaveURL(new RegExp(`/scan\\?id=${RUNNING}$`));
  await expect(
    page.getByRole('heading', { level: 1, name: 'olajaido/haunted-house' }),
  ).toBeFocused();
  await expect(page.getByRole('heading', { name: 'The lantern path' })).toBeVisible();
  await axe(page, 'the exhumation page');
  for (const word of ['Digging up the lockfiles', 'Tagging the bodies', 'Tracing the roots']) {
    await expect(page.getByRole('status').filter({ hasText: word })).toBeAttached();
  }
  await expect(page.getByText('0 of 208 examined', { exact: true })).toBeVisible();
  await axe(page, 'the exhumation page, during the autopsy');
  await expect(page.getByText('104 of 208 examined', { exact: true })).toBeVisible();
  await expect(page.getByText('208 of 208 examined', { exact: true })).toBeVisible();
  await expect(page.getByText(/%/)).toHaveCount(0);

  // The graveyard
  await expect(page.getByText(/Exhumation complete · 23 Nov 2026/)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/scan\\?id=${RUNNING}$`));
  await expect(
    page.getByRole('heading', { level: 1, name: 'olajaido/haunted-house' }),
  ).toBeFocused();
  await expect(
    page.getByText('208 dependencies dug up across 2 plots. 17 dead, 2 cursed, 84 ailing.'),
  ).toBeVisible();
  const root = page.getByRole('region', { name: 'The root plot' });
  await expect(root.getByRole('link', { name: /priority \d+ of 137/ })).toHaveCount(24);
  await expect(root.getByRole('link', { name: /^see them in Lights on/ })).toBeVisible();
  await expect(root.getByText(/^Also in this plot: /)).toBeVisible();
  await axe(page, 'the graveyard');
  await page.getByRole('button', { name: 'Cursed, 2' }).click();
  await expect(root.getByRole('link', { name: /priority/ })).toHaveCount(2);
  await page.getByRole('button', { name: 'Cursed, 2' }).click();

  // Lights on: sort and filter
  await page.getByRole('button', { name: 'Lights on' }).click();
  const table = page.getByRole('table');
  await expect(table).toBeVisible();
  await expect(page).toHaveURL(/view=table/);
  await axe(page, 'the Lights on table');
  const rows = table.getByRole('row');
  await expect(rows).toHaveCount(1 + 137);
  await page.getByRole('button', { name: 'Package' }).click();
  await expect(page.getByRole('columnheader', { name: /Package/ })).toHaveAttribute(
    'aria-sort',
    'ascending',
  );
  await expect(rows.nth(1).getByRole('link')).toHaveText('agent-base@6.0.2');
  await page.getByRole('button', { name: 'Dead, 17' }).click();
  await expect(rows).toHaveCount(1 + 17);

  // The certificate
  await page.getByRole('button', { name: 'Dead, 17' }).click();
  await table.getByRole('link', { name: 'lodash.template@3.6.2' }).click();
  await expect(page).toHaveURL(/\/grave\?scan=.*purl=pkg%3Anpm%2Flodash\.template%403\.6\.2$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Certificate of Death' })).toBeFocused();
  await expect(
    page.getByRole('link', { name: /Read the notice on npmjs\.com/ }).first(),
  ).toHaveAttribute('href', 'https://www.npmjs.com/package/lodash.template/v/3.6.2');
  await expect(page.getByText('It arrived with gulp-util.')).toBeVisible();
  await axe(page, 'the certificate');

  // Back, to the remembered view (the table)
  await page.getByRole('link', { name: 'Back to olajaido/haunted-house' }).click();
  await expect(page).toHaveURL(new RegExp(`/scan\\?id=${RUNNING}`));
  await expect(page.getByRole('table')).toBeVisible();

  // An unknown scan
  await page.goto(`/scan?id=${UNKNOWN}`);
  await expect(
    page.getByRole('heading', { level: 1, name: 'This plot is not on the map' }),
  ).toBeVisible();
  await expect(page.getByText(/30 days/)).toBeVisible();
  await axe(page, 'the 404 of an unknown scan');
});

test('a link opened directly shows the same screen (results, and a certificate of a scoped package)', async ({
  page,
}) => {
  await page.goto(`/scan?id=${DONE}`);
  await expect(page.getByText(/Exhumation complete · 23 Nov 2026/)).toBeVisible();
  await axe(page, 'results opened directly');

  await page.goto(grave(DONE, SCOPED));
  await expect(page.getByRole('heading', { level: 1, name: 'Certificate of Death' })).toBeVisible();
  await expect(page.getByText('@babel/core', { exact: false }).first()).toBeVisible();
  await expect(page).toHaveURL(/purl=pkg%3Anpm%2F%2540babel%2Fcore%407\.0\.0$/);
  await expect(page.getByText('Not recorded').first()).toBeVisible();
  await axe(page, 'a sparse certificate');

  await page.goto(grave(DONE, 'pkg:npm/not-in-this-scan@1.0.0'));
  await expect(
    page.getByRole('heading', { level: 1, name: 'No such grave in this plot' }),
  ).toBeVisible();
  await page.goto('/grave?scan=nope&purl=nope');
  await expect(
    page.getByRole('heading', { level: 1, name: 'No such grave in this plot' }),
  ).toBeVisible();
  await axe(page, 'the 404 of a grave');
});

test('a refused repository stays on the landing page and takes focus', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Public GitHub repository').fill('https://gitlab.com/a/b');
  await page.getByRole('button', { name: 'Exhume' }).click();
  await expect(page.getByText(/That is not a grave site/)).toBeVisible();
  await expect(page.getByLabel('Public GitHub repository')).toBeFocused();
  await expect(page).toHaveURL(/\/$/);
  await axe(page, 'the landing page with an error');
});

test.describe('360 px wide', () => {
  test.use({ viewport: { width: 360, height: 800 } });

  test('no page scrolls sideways, and the table scrolls inside its own region', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await noSideScroll(page, 'the landing page');
    await axe(page, 'the landing page at 360 px');

    await page.goto(`/scan?id=${DONE}`);
    await expect(page.getByText(/Exhumation complete · /)).toBeVisible();
    await noSideScroll(page, 'the graveyard');
    await page.getByRole('button', { name: 'Lights on' }).click();
    await expect(page.getByRole('table')).toBeVisible();
    await noSideScroll(page, 'the Lights on table');
    const region = page.getByRole('region', { name: 'Register of graves' });
    expect(await region.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
    await axe(page, 'the table at 360 px');

    await page.goto(
      `/grave?${new URLSearchParams({ scan: DONE, purl: 'pkg:npm/lodash.template@3.6.2' })}`,
    );
    await expect(
      page.getByRole('heading', { level: 1, name: 'Certificate of Death' }),
    ).toBeVisible();
    await noSideScroll(page, 'the certificate');
    await axe(page, 'the certificate at 360 px');

    await page.goto(`/scan?id=${UNKNOWN}`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await noSideScroll(page, 'the 404');

    await page.goto(`/scan?id=${RUNNING}`);
    await expect(page.getByRole('heading', { name: 'The lantern path' })).toBeVisible();
    await noSideScroll(page, 'the exhumation page');
  });
});

test.describe('reduced motion', () => {
  test.use({ reducedMotion: 'reduce' });

  test('nothing animates on the landing page, the exhumation or the results', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    expect(await animations(page)).toBe(0);

    await page.goto(`/scan?id=${RUNNING}`);
    await expect(page.getByRole('heading', { name: 'The lantern path' })).toBeVisible();
    expect(await animations(page)).toBe(0);

    await page.goto(`/scan?id=${DONE}`);
    await expect(page.getByText(/Exhumation complete · /)).toBeVisible();
    await page.getByRole('link', { name: /priority 1 of 138/ }).hover();
    expect(await animations(page)).toBe(0);
  });
});

test.describe('with motion allowed', () => {
  test.use({ reducedMotion: 'no-preference' });

  test('the scene does move (so the reduced motion test proves something)', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    expect(await animations(page)).toBeGreaterThan(0);
  });
});

/** The live cascade, in a real browser: what the person sees, not what the class names say. */
test.describe('the results page as drawn', () => {
  async function results(page: Page, width = 1440) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/scan?id=${DONE}`);
    await page.getByText(/Exhumation complete · /).waitFor();
    await settle(page);
  }

  /** The contrast of an element's text colour against the first opaque background behind it. */
  const contrastOf = (selector: string) => (page: Page) =>
    page.evaluate((sel) => {
      const rgb = (v: string) => (v.match(/[\d.]+/g) ?? []).map(Number);
      const lum = ([r, g, b]: number[]) => {
        const f = (c: number) => {
          const s = c / 255;
          return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
        };
        return 0.2126 * f(r!) + 0.7152 * f(g!) + 0.0722 * f(b!);
      };
      const el = document.querySelector(sel);
      if (!el) return { found: false, ratio: 0, fg: '', bg: '' };
      const fg = getComputedStyle(el).color;
      let node: Element | null = el;
      let bg = 'rgb(13, 15, 19)';
      while (node) {
        const c = getComputedStyle(node).backgroundColor;
        const a = rgb(c)[3];
        if (c !== 'rgba(0, 0, 0, 0)' && (a === undefined || a === 1)) {
          bg = c;
          break;
        }
        node = node.parentElement;
      }
      const [l1, l2] = [lum(rgb(fg)), lum(rgb(bg))];
      return { found: true, ratio: (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05), fg, bg };
    }, selector);

  test('"Exhume another" and the names on the toe tags are readable text, not text the colour of its background', async ({
    page,
  }) => {
    await results(page);
    const button = await contrastOf('header a[href="/"].bg-bone')(page);
    expect(button, JSON.stringify(button)).toMatchObject({ found: true });
    expect(button.ratio, JSON.stringify(button)).toBeGreaterThanOrEqual(4.5);
    expect(await page.getByRole('link', { name: 'Exhume another' }).innerText()).toBe(
      'Exhume another',
    );
    const name = await contrastOf('#dig-first-title ~ ul li a > span.font-mono')(page);
    expect(name, JSON.stringify(name)).toMatchObject({ found: true });
    expect(name.ratio, JSON.stringify(name)).toBeGreaterThanOrEqual(4.5);
    const tag = await contrastOf('#dig-first-title ~ ul li a > span:last-child')(page);
    expect(tag.ratio, JSON.stringify(tag)).toBeGreaterThanOrEqual(4.5);
  });

  test('a heading that script focuses draws no ring, and a stone reached by the keyboard does', async ({
    page,
  }) => {
    await results(page);
    const h1 = page.getByRole('heading', { level: 1 });
    await expect(h1).toBeFocused();
    const heading = await h1.evaluate((el) => {
      const s = getComputedStyle(el);
      return { style: s.outlineStyle, width: s.outlineWidth };
    });
    expect(heading.style === 'none' || heading.width === '0px', JSON.stringify(heading)).toBe(true);
    const main = await page.locator('main').evaluate((el) => getComputedStyle(el).outlineStyle);
    expect(main).toBe('none');
    for (let i = 0; i < 60; i++) {
      await page.keyboard.press('Tab');
      if (await page.evaluate(() => document.activeElement?.hasAttribute('data-stone'))) break;
    }
    const stone = await page.evaluate(() => {
      const el = document.activeElement!;
      const s = getComputedStyle(el);
      return { stone: el.hasAttribute('data-stone'), style: s.outlineStyle, width: s.outlineWidth };
    });
    expect(stone).toEqual({ stone: true, style: 'solid', width: '2px' });
  });

  test('the cursed glow stays faint while it pulses', async ({ page }) => {
    await results(page);
    const seen = await page.evaluate(async () => {
      const glow = document.querySelector('svg g.gy-glow > ellipse');
      if (!glow) return null;
      const own = Number(getComputedStyle(glow).opacity);
      const out: number[] = [];
      for (let i = 0; i < 12; i++) {
        let product = own;
        for (
          let n: Element | null = glow.parentElement;
          n && n.tagName !== 'BODY';
          n = n.parentElement
        )
          product *= Number(getComputedStyle(n).opacity);
        out.push(product);
        await new Promise((r) => setTimeout(r, 350));
      }
      return { own, min: Math.min(...out), max: Math.max(...out) };
    });
    expect(seen).not.toBeNull();
    expect(seen!.own).toBeLessThanOrEqual(0.2);
    expect(seen!.max, JSON.stringify(seen)).toBeLessThanOrEqual(0.2);
    expect(seen!.min, JSON.stringify(seen)).toBeGreaterThanOrEqual(0.08);
  });

  for (const width of [768, 1024, 1440, 1920]) {
    test(`no star or moon touches the text of the summary at ${width} px`, async ({ page }) => {
      await results(page, width);
      const hit = await page.evaluate(() => {
        const summary = document.querySelector('section[aria-label="Scan summary"]')!;
        const circles = [...summary.querySelectorAll('[data-testid="sky-objects"] circle')].map(
          (c) => c.getBoundingClientRect(),
        );
        const texts: { text: string; r: DOMRect }[] = [];
        const walker = document.createTreeWalker(summary, NodeFilter.SHOW_TEXT);
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
          if (!n.textContent?.trim() || n.parentElement?.closest('svg')) continue;
          const range = document.createRange();
          range.selectNodeContents(n);
          for (const r of range.getClientRects()) texts.push({ text: n.textContent.trim(), r });
        }
        const touching: string[] = [];
        for (const c of circles)
          for (const { text, r } of texts)
            if (c.left < r.right && c.right > r.left && c.top < r.bottom && c.bottom > r.top)
              touching.push(text);
        return { circles: circles.length, texts: texts.length, touching };
      });
      expect(hit.texts).toBeGreaterThan(5);
      expect(hit.touching).toEqual([]);
      // The moon and stars are drawn on wide screens only, and are always behind the text layer.
      if (width < 768) expect(hit.circles).toBe(0);
    });
  }

  test('the fence stands on the stones panel, and the hill is lighter than the sky', async ({
    page,
  }) => {
    await results(page);
    const geometry = await page.evaluate(() => {
      const plot = [...document.querySelectorAll('section[aria-labelledby]')].find((s) =>
        s.querySelector('h2')?.textContent?.includes('root plot'),
      )!;
      const svg = plot.querySelector('svg')!;
      const panel = svg.parentElement!;
      const box = svg.getBoundingClientRect();
      const panelBox = panel.getBoundingClientRect();
      const sectionBox = plot.getBoundingClientRect();
      const unit = box.height / 260;
      const hill = svg.querySelector('path')!.getAttribute('fill');
      return {
        fenceFoot: box.top + 200 * unit - panelBox.top,
        fenceTopInside: box.top + 150 * unit >= sectionBox.top,
        hill,
        sky: getComputedStyle(plot).backgroundColor,
      };
    });
    expect(Math.abs(geometry.fenceFoot)).toBeLessThanOrEqual(1);
    expect(geometry.fenceTopInside).toBe(true);
    expect(geometry.hill?.toLowerCase()).toBe('#1e232b');
    expect(geometry.sky).toBe('rgb(18, 22, 32)');
  });

  test('the whole results page has no axe violation, with the new art in place', async ({
    page,
  }) => {
    await results(page);
    await axe(page, 'results with the new backdrop and sky');
  });
});
