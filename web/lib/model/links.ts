import type { EvidenceLink } from '@/lib/api/types';

/** The hosts an evidence link may point at (ui-core UI-CERT-4). The server builds the links on the same five. */
export const LINK_HOSTS: readonly string[] = [
  'www.npmjs.com',
  'pypi.org',
  'github.com',
  'osv.dev',
  'deps.dev',
];

/**
 * The URL when it is `https` on an allowed host, with no user information, else null. Defence in depth: the server
 * already builds links from a fixed set of hosts, and a link that fails here is not rendered.
 */
export function safeLink(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' || u.username || u.password || !LINK_HOSTS.includes(u.hostname))
      return null;
    return u.href;
  } catch {
    return null;
  }
}

/** Link text from the kind, the host and whether the signal it covers says the package is gone (design 5.6). */
export function linkLabel(link: Pick<EvidenceLink, 'kind' | 'url'>, flagged: boolean): string {
  let host = '';
  try {
    host = new URL(link.url).hostname.replace(/^www\./, '');
  } catch {
    return 'Read the source';
  }
  switch (link.kind) {
    case 'registry':
      return flagged ? `Read the notice on ${host}` : `View on ${host}`;
    case 'repository':
      return `See the repository on ${host}`;
    case 'advisory':
      return `Read the advisory on ${host}`;
    case 'deps_dev':
      return `See the scores on ${host}`;
  }
}
