import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createClient } from '@/lib/api/client';
import type { Certificate } from '@/lib/api/types';
import { expectNoViolations } from '@/lib/test/axe';
import { mockApi, server } from '@/mocks/node';
import { manyGraves, minimalCertificate } from '@/mocks/fixtures/builders';
import {
  hauntedGraves,
  hauntedScan,
  HAUNTED_SCAN_ID,
  lodashCertificate,
} from '@/mocks/fixtures/haunted-house';
import { http, HttpResponse } from 'msw';
import { CertificatePage } from './certificate-page';
import { descentSentence } from './descent';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const client = createClient({ baseUrl: 'https://api.test' });
const PURL = 'pkg:npm/lodash.template@3.6.2';
const open = (purl = PURL, scan = HAUNTED_SCAN_ID) =>
  window.history.replaceState(null, '', `/grave?${new URLSearchParams({ scan, purl }).toString()}`);

beforeEach(() => {
  window.localStorage.clear();
  open();
});

async function page() {
  render(<CertificatePage client={client} />);
  await screen.findByRole('heading', { level: 1 });
}

const field = (label: string) => screen.getByText(label, { selector: 'dt' }).parentElement!;

describe('the certificate of lodash.template@3.6.2 (the real capture)', () => {
  it('prints the fields of the payload', async () => {
    mockApi();
    await page();
    expect(screen.getByRole('heading', { level: 1, name: 'Certificate of Death' })).toHaveFocus();
    expect(screen.getByText(/issued on the evidence, 22 Nov 2026/)).toBeInTheDocument();
    expect(field('Name of the deceased')).toHaveTextContent('lodash.template@3.6.2');
    expect(field('Pronounced')).toHaveTextContent('Dead · declared');
    expect(field('Complications')).toHaveTextContent('Cursed · known vulnerability, no fix');
    expect(field('Cause of death')).toHaveTextContent(
      'Declared dead: its source reports it as deprecated, archived or retired.',
    );
    expect(field('Cause of death')).toHaveTextContent(
      'A known vulnerability affects this version and no fixed version exists.',
    );
    expect(field('Ecosystem')).toHaveTextContent('npm');
    expect(field('Place of rest')).toHaveTextContent(
      'service "." , runtime scope'.replace(' ,', ','),
    );
    expect(field('Mortality')).toHaveTextContent('90 / 100');
    expect(field('Confidence')).toHaveTextContent('1.0 · priority 108.0');
    expect(field('Last released')).toHaveTextContent('1 Apr 2026');
    expect(screen.queryByText('Born')).toBeNull();
    expect(screen.getByText(`scan ${HAUNTED_SCAN_ID} · model v2`)).toBeInTheDocument();
    expect(document.title).toBe('lodash.template@3.6.2 · Graveyard');
  });

  it('draws the line of descent through gulp-util and says it arrived with it', async () => {
    mockApi();
    await page();
    const path = screen.getByRole('list', { name: 'Path' });
    const items = within(path).getAllByRole('listitem');
    expect(items.map((i) => i.textContent?.replace('→', ''))).toEqual([
      'haunted-house',
      'gulp-util@3.0.8dead',
      'lodash.template@3.6.2',
    ]);
    expect(screen.getByText('It arrived with gulp-util.')).toBeInTheDocument();
  });

  it('badges a package of the path only when the graves list has it', async () => {
    mockApi();
    await page();
    await waitFor(() =>
      expect(
        within(screen.getByRole('list', { name: 'Path' })).getByText('dead'),
      ).toBeInTheDocument(),
    );
    expect(
      within(screen.getByRole('list', { name: 'Path' })).getAllByText(/dead|ailing/),
    ).toHaveLength(1);
  });

  it('shows the evidence with kinds, values and link-outs, and no text from a source', async () => {
    mockApi();
    await page();
    const evidence = screen.getByRole('region', { name: 'Evidence on file' });
    expect(within(evidence).getAllByRole('listitem').length).toBeGreaterThanOrEqual(11);
    expect(within(evidence).getByText('Declared dead')).toBeInTheDocument();
    const notice = within(evidence).getAllByRole('link', { name: /Read the notice on npmjs.com/ });
    expect(notice[0]).toHaveAttribute(
      'href',
      'https://www.npmjs.com/package/lodash.template/v/3.6.2',
    );
    expect(notice[0]).toHaveAttribute('rel', 'noopener noreferrer');
    const repos = within(evidence).getAllByRole('link', {
      name: /See the repository on github.com/,
    });
    expect(repos.length).toBeGreaterThan(1);
    expect(repos[0]).toHaveAttribute('href', 'https://github.com/lodash/lodash');
    // the same page is offered on several rows, and each link says which signal it is about
    expect(new Set(repos.map((r) => r.textContent)).size).toBe(repos.length);
    expect(
      within(evidence).getAllByRole('link', { name: /See the scores on deps.dev/ }).length,
    ).toBeGreaterThan(0);
    const advisory = within(evidence).getByRole('link', { name: /Read the advisory on osv.dev/ });
    expect(advisory).toHaveAttribute('href', 'https://osv.dev/vulnerability/GHSA-35jh-r3h4-6jhm');
    expect(evidence).toHaveTextContent('GHSA-35jh-r3h4-6jhm');
    expect(evidence).toHaveTextContent('no fix');
    expect(evidence).toHaveTextContent('published 2021-05-06');
    expect(evidence).not.toHaveTextContent(/api\.deps\.dev|registry\.npmjs\.org|https?:\/\//);
  });

  it('draws nothing for what the API does not return: no "Born", no "Buried alongside", no rites controls', async () => {
    mockApi();
    await page();
    expect(screen.queryByText('Born')).toBeNull();
    expect(screen.queryByText(/Buried alongside/i)).toBeNull();
    expect(screen.queryByRole('complementary')).toBeNull();
    expect(screen.queryByText(/rites|draft PR/i)).toBeNull();
    expect(document.body.textContent).not.toMatch(/not in the API|API yet|yet\b/i);
  });

  it('links back to the scan by name and copies the certificate link', async () => {
    mockApi();
    await page();
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Back to olajaido/haunted-house' })).toHaveAttribute(
        'href',
        `/scan?id=${HAUNTED_SCAN_ID}`,
      ),
    );
    expect(screen.getByRole('button', { name: 'Copy certificate link' })).toBeInTheDocument();
  });

  it('has a decorative seal and no axe violations', async () => {
    mockApi();
    const { container } = render(<CertificatePage client={client} />);
    await screen.findByRole('heading', { level: 1 });
    expect(container.querySelector('svg text')?.closest('svg')).toHaveAttribute(
      'aria-hidden',
      'true',
    );
    await expectNoViolations(container, { wholePage: true });
  });
});

describe('the words of the evidence', () => {
  /** An internal identifier: lower-case words joined by underscores (as_of, s5_committers). */
  const IDENTIFIER = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/;
  it('has no internal identifier in the real capture, and writes the date for as_of', async () => {
    mockApi();
    await page();
    const evidence = screen.getByRole('region', { name: 'Evidence on file' });
    expect(evidence).toHaveTextContent('distinct commit authors in the 12 months to 22 Nov 2026');
    expect(evidence.textContent).not.toMatch(IDENTIFIER);
    expect(document.body.textContent).not.toMatch(IDENTIFIER);
  });
  it('has none in the notes either: signal keys become names, as_of becomes the date', async () => {
    const cert: Certificate = {
      ...lodashCertificate,
      warnings: [
        {
          code: 'PARTIAL',
          source: 'github_graphql',
          status: null,
          detail: 'commit authors were counted to as_of from a partial page',
          signals: ['s5_committers', 's3_last_push_at'],
        },
      ],
    };
    mockApi({ certificates: { [HAUNTED_SCAN_ID]: { [cert.purl]: cert } } });
    await page();
    const notes = screen.getByRole('region', { name: 'Notes on the evidence' });
    expect(notes).toHaveTextContent('github graphql');
    expect(notes).toHaveTextContent('counted to 22 Nov 2026 from a partial page');
    expect(notes).toHaveTextContent(
      '(affects committers in the last 12 months, last push to the repository)',
    );
    expect(document.body.textContent).not.toMatch(IDENTIFIER);
  });
});

describe('a certificate with every optional field empty', () => {
  const sparse = (): Certificate => ({
    ...minimalCertificate(manyGraves(1)[0]!),
    purl: 'pkg:npm/bare@1.0.0',
    state: 'unscored',
    priority: null,
    mortality: null,
    confidence: null,
  });

  it('says "Not recorded" and shows no placeholder from the mockups', async () => {
    const cert = sparse();
    mockApi({
      certificates: { [HAUNTED_SCAN_ID]: { [cert.purl]: cert } },
      graves: { [HAUNTED_SCAN_ID]: [] },
    });
    open(cert.purl);
    await page();
    expect(
      screen.getByRole('heading', { level: 1, name: 'Certificate of Condition' }),
    ).toBeInTheDocument();
    expect(field('Mortality')).toHaveTextContent('Not recorded');
    expect(field('Confidence')).toHaveTextContent('Not recorded');
    expect(field('Last released')).toHaveTextContent('Not recorded');
    expect(screen.getByText(/No path to this package was kept/)).toBeInTheDocument();
    const evidence = screen.getByRole('region', { name: 'Evidence on file' });
    expect(within(evidence).getAllByText('Not recorded')).toHaveLength(11);
    expect(screen.queryByRole('region', { name: 'Notes on the evidence' })).toBeNull();
    const text = document.body.textContent ?? '';
    for (const placeholder of ['[notice text', '[advisory', '142 of', '68%', 'DECEASED'])
      expect(text).not.toContain(placeholder);
  });

  it('has no axe violations', async () => {
    const cert = sparse();
    mockApi({
      certificates: { [HAUNTED_SCAN_ID]: { [cert.purl]: cert } },
      graves: { [HAUNTED_SCAN_ID]: [] },
    });
    open(cert.purl);
    const { container } = render(<CertificatePage client={client} />);
    await screen.findByRole('heading', { level: 1 });
    await expectNoViolations(container, { wholePage: true });
  });
});

describe('other certificates', () => {
  it('writes a wounded, alive package as a certificate of condition with its own seal word', async () => {
    const g = hauntedGraves.items.find((x) => x.state === 'alive' && x.wounded)!;
    mockApi();
    open(g.purl);
    await page();
    expect(
      screen.getByRole('heading', { level: 1, name: 'Certificate of Condition' }),
    ).toBeInTheDocument();
    expect(field('Complications')).toHaveTextContent('Wounded · upgrade advised');
    expect(field('Pronounced')).toHaveTextContent('Alive');
    expect(document.querySelector('svg text')?.textContent).toBe('WOUNDED');
  });

  it('opens a scoped npm purl', async () => {
    const scoped = { ...manyGraves(1)[0]!, purl: 'pkg:npm/%40babel/core@7.0.0' };
    mockApi({
      scans: { [HAUNTED_SCAN_ID]: hauntedScan },
      graves: { [HAUNTED_SCAN_ID]: [scoped] },
      certificates: {},
    });
    open(scoped.purl);
    await page();
    expect(field('Name of the deceased')).toHaveTextContent('@babel/core@7.0.0');
  });
});

describe('the sentence of the descent', () => {
  const base = {
    direct: false,
    via: 'pkg:npm/a@1.0.0',
    pathCount: 1,
    examplePaths: [{ service: '.', nodes: ['npm/a@1.0.0', 'npm/b@1'] }],
  };
  it.each([
    [
      { ...base, direct: true, via: null, examplePaths: [{ service: '.', nodes: ['npm/b@1'] }] },
      'You chose this package yourself.',
    ],
    [base, 'It arrived with a.'],
    [{ ...base, pathCount: 3 }, 'It arrived with a. 3 paths lead here, showing 1.'],
    [
      { ...base, pathCount: 2, examplePaths: [base.examplePaths[0]!, base.examplePaths[0]!] },
      'It arrived with a. 2 paths lead here.',
    ],
    [{ ...base, via: null }, 'It arrived as a transitive dependency.'],
    [
      { ...base, via: null, examplePaths: [] },
      'It is a transitive dependency. No path to it was kept.',
    ],
  ])('%j', (c, text) => expect(descentSentence(c as never)).toBe(text));
});

describe('failures', () => {
  it.each(['not-a-purl', '', 'npm/x@1'])(
    'the link %j is a 404 without any request',
    async (purl) => {
      const api = mockApi();
      window.history.replaceState(
        null,
        '',
        `/grave?scan=${HAUNTED_SCAN_ID}&purl=${encodeURIComponent(purl)}`,
      );
      render(<CertificatePage client={client} />);
      expect(
        await screen.findByRole('heading', { level: 1, name: 'No such grave in this plot' }),
      ).toBeInTheDocument();
      expect(api.calls).toEqual([]);
      expect(screen.getByRole('link', { name: 'Back to the scan' })).toHaveAttribute(
        'href',
        `/scan?id=${HAUNTED_SCAN_ID}`,
      );
    },
  );

  it('a bad scan id is a 404 that links home', async () => {
    mockApi();
    window.history.replaceState(null, '', `/grave?scan=nope&purl=${encodeURIComponent(PURL)}`);
    render(<CertificatePage client={client} />);
    expect(
      await screen.findByRole('heading', { level: 1, name: 'No such grave in this plot' }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Back to the gate' })[0]).toHaveAttribute(
      'href',
      '/',
    );
  });

  it('a package that is not in the scan is a 404 with a way back by name', async () => {
    mockApi();
    open('pkg:npm/not-in-this-scan@1.0.0');
    render(<CertificatePage client={client} />);
    expect(
      await screen.findByRole('heading', { level: 1, name: 'No such grave in this plot' }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole('link', { name: 'Back to olajaido/haunted-house' }),
    ).toBeInTheDocument();
  });

  it('an invalid package link (400) says the marker is not valid', async () => {
    mockApi();
    server.use(
      http.get(/\/graves\/[^/]+$/, () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Bad request',
            status: 400,
            detail: 'The package URL is not valid.',
          },
          { status: 400 },
        ),
      ),
    );
    render(<CertificatePage client={client} />);
    expect(
      await screen.findByRole('heading', { level: 1, name: 'That grave marker is not valid' }),
    ).toBeInTheDocument();
  });

  it('a failing API offers a retry that works', async () => {
    let down = true;
    mockApi();
    server.use(
      http.get(/\/graves\/[^/]+$/, () =>
        down ? HttpResponse.error() : HttpResponse.json(lodashCertificate),
      ),
    );
    render(<CertificatePage client={client} />);
    expect(
      await screen.findByRole('heading', { level: 1, name: 'The path is out of reach' }),
    ).toBeInTheDocument();
    down = false;
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Certificate of Death' }),
    ).toBeInTheDocument();
  });

  it('refuses to render a link on another host', async () => {
    const evil: Certificate = {
      ...lodashCertificate,
      evidenceLinks: [
        { kind: 'registry', url: 'https://evil.example/x', signals: ['s2_latest_release_at'] },
        { kind: 'repository', url: 'javascript:alert(1)', signals: ['s3_last_push_at'] },
        { kind: 'deps_dev', url: 'http://deps.dev/npm/x/1', signals: ['s4_maintained'] },
      ],
    };
    mockApi({ certificates: { [HAUNTED_SCAN_ID]: { [PURL]: evil } } });
    await page();
    const evidence = screen.getByRole('region', { name: 'Evidence on file' });
    expect(within(evidence).queryAllByRole('link')).toHaveLength(0);
    expect(document.body.innerHTML).not.toContain('evil.example');
    expect(document.body.innerHTML).not.toContain('javascript:');
  });
});
