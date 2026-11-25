import { STATE_KEYS } from './state-key';

/** The ID of a scan: a ULID, a dash and 16 hex characters (scan-backend SB-API-2). */
export const SCAN_ID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}-[0-9a-f]{16}$/;

export type View = 'scene' | 'table';
export type SortKey = 'priority' | 'package' | 'state';
export type SortDir = 'asc' | 'desc';
export const FILTER_KEYS = ['dead', 'cursed', 'ailing', 'resting', 'wounded'] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

/** The view state of the scan page. It lives in the query string, so a link shows the same screen. */
export interface ViewState {
  view?: View;
  state?: FilterKey;
  service?: string;
  sort: SortKey;
  dir: SortDir;
}

export const DEFAULT_VIEW_STATE: ViewState = { sort: 'priority', dir: 'desc' };

const SORT_KEYS: readonly string[] = ['priority', 'package', 'state'];

export function parseViewState(params: URLSearchParams): ViewState {
  const view = params.get('view');
  const state = params.get('state');
  const sort = params.get('sort');
  const dir = params.get('dir');
  const service = params.get('service');
  return {
    view: view === 'scene' || view === 'table' ? view : undefined,
    state: (FILTER_KEYS as readonly string[]).includes(state ?? '')
      ? (state as FilterKey)
      : undefined,
    service: service ? service : undefined,
    sort: SORT_KEYS.includes(sort ?? '') ? (sort as SortKey) : DEFAULT_VIEW_STATE.sort,
    dir:
      dir === 'asc' || dir === 'desc'
        ? dir
        : defaultDir(SORT_KEYS.includes(sort ?? '') ? (sort as SortKey) : 'priority'),
  };
}

/** Priority starts with the highest, the others with the first. */
export function defaultDir(sort: SortKey): SortDir {
  return sort === 'priority' ? 'desc' : 'asc';
}

/** The query string of the scan page for a view state; defaults are left out. */
export function viewStateSearch(
  state: Partial<ViewState>,
  base?: URLSearchParams,
): URLSearchParams {
  const params = new URLSearchParams(base);
  for (const key of ['view', 'state', 'service', 'sort', 'dir']) params.delete(key);
  if (state.view) params.set('view', state.view);
  if (state.state) params.set('state', state.state);
  if (state.service) params.set('service', state.service);
  const sort = state.sort ?? 'priority';
  if (sort !== 'priority') params.set('sort', sort);
  if ((state.dir ?? defaultDir(sort)) !== defaultDir(sort)) params.set('dir', state.dir as SortDir);
  return params;
}

export function scanHref(scanId: string, state: Partial<ViewState> = {}): string {
  const params = new URLSearchParams({ id: scanId });
  for (const [k, v] of viewStateSearch(state)) params.set(k, v);
  return `/scan?${params.toString()}`;
}

export function graveHref(scanId: string, purl: string): string {
  return `/grave?${new URLSearchParams({ scan: scanId, purl }).toString()}`;
}

export type ScanQuery = { ok: true; scanId: string } | { ok: false };
export type GraveQuery = { ok: true; scanId: string; purl: string } | { ok: false };

/** `?id=<scanId>`. A missing or malformed ID is an unknown link, resolved without calling the API (UI-RT-2). */
export function parseScanQuery(search: string): ScanQuery {
  const id = new URLSearchParams(search).get('id');
  return id !== null && SCAN_ID_PATTERN.test(id) ? { ok: true, scanId: id } : { ok: false };
}

/** `?scan=<scanId>&purl=<encoded purl>`. Each value is decoded exactly once, by `URLSearchParams`. */
export function parseGraveQuery(search: string): GraveQuery {
  const params = new URLSearchParams(search);
  const scanId = params.get('scan');
  const purl = params.get('purl');
  if (scanId === null || !SCAN_ID_PATTERN.test(scanId)) return { ok: false };
  if (purl === null || !purl.startsWith('pkg:') || purl.length > 400) return { ok: false };
  return { ok: true, scanId, purl };
}

export function isStateKey(value: string): boolean {
  return (STATE_KEYS as readonly string[]).includes(value);
}
