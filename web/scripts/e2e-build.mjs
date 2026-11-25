// After `next build` with NEXT_PUBLIC_API_MOCKING=enabled: put the MSW service worker next to the export, so the
// browser can register it at /mockServiceWorker.js. The worker is never in `public/`, so a production build cannot
// contain it (ui-core UI-STK-8, design 14).
import { copyFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const worker = resolve(root, 'node_modules/msw/lib/mockServiceWorker.js');
const out = resolve(root, 'out');
if (!existsSync(worker)) throw new Error('msw is not installed: run npm ci');
if (!existsSync(out)) throw new Error('out/ does not exist: run next build first');
copyFileSync(worker, resolve(out, 'mockServiceWorker.js'));
console.log('copied mockServiceWorker.js into out/');
