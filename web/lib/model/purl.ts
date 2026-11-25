export interface DisplayPurl {
  type: string;
  ecosystemLabel: string;
  namespace?: string;
  name: string;
  /** `@scope/name` or `name`, as the registry spells it. */
  fullName: string;
  version?: string;
}

function decode(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

const LABELS: Record<string, string> = { npm: 'npm', pypi: 'PyPI' };

/**
 * A purl split for display. It drops qualifiers and the subpath and never throws: text that is not a purl comes
 * back whole as the name. The server validates purls; this is only for showing them.
 */
export function parseDisplayPurl(purl: string): DisplayPurl {
  const whole: DisplayPurl = {
    type: 'unknown',
    ecosystemLabel: 'unknown',
    name: purl,
    fullName: purl,
  };
  if (!purl.startsWith('pkg:')) return whole;
  const bare = purl.slice(4).split('#')[0]?.split('?')[0] ?? '';
  const slash = bare.indexOf('/');
  if (slash <= 0) return whole;
  const type = bare.slice(0, slash).toLowerCase();
  let rest = bare.slice(slash + 1);
  let version: string | undefined;
  const at = rest.lastIndexOf('@');
  if (at > 0) {
    version = decode(rest.slice(at + 1)) || undefined;
    rest = rest.slice(0, at);
  }
  const parts = rest
    .split('/')
    .map(decode)
    .filter((p) => p.length > 0);
  const name = parts.pop();
  if (!name) return whole;
  const namespace = parts.length > 0 ? parts.join('/') : undefined;
  return {
    type,
    ecosystemLabel: LABELS[type] ?? type,
    namespace,
    name,
    fullName: namespace ? `${namespace}/${name}` : name,
    version,
  };
}

/** A package key of an example path (a canonical purl without `pkg:`). */
export function parsePackageKey(key: string): DisplayPurl {
  return parseDisplayPurl(`pkg:${key}`);
}
