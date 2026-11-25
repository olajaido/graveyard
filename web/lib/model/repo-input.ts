const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const NAME = /^[A-Za-z0-9._-]{1,100}$/;

export type RepoResult = { ok: true; repo: string } | { ok: false };

/**
 * `owner/name` from what a person pastes: `owner/name`, `github.com/owner/name` or
 * `https://github.com/owner/name(.git)(/)`. The rules mirror `exhume/validate.py` `parse_repo`; the server stays the
 * authority. Anything else (a deeper path, a query, a fragment, another host) is refused.
 */
export function normaliseRepo(input: string): RepoResult {
  let text = input.trim();
  if (/[?#\s]/.test(text)) return { ok: false };
  text = text.replace(/^https?:\/\//i, '').replace(/^www\./i, '');
  text = text.replace(/^github\.com\//i, '');
  text = text.replace(/\/+$/, '');
  const parts = text.split('/');
  if (parts.length !== 2) return { ok: false };
  const [owner, rawName] = parts as [string, string];
  const name = rawName.length > 4 && rawName.endsWith('.git') ? rawName.slice(0, -4) : rawName;
  if (!OWNER.test(owner) || !NAME.test(name) || name === '.' || name === '..') return { ok: false };
  return { ok: true, repo: `${owner}/${name}` };
}
