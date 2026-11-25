// Checks the production export (ui-core UI-STK-4 and UI-STK-8): it must not talk to Google Fonts, and it must hold no
// mock code. Run after `npm run build`. Exit code 1 with the offending files when a check fails.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

export const FORBIDDEN = [
  { pattern: /fonts\.googleapis\.com|fonts\.gstatic\.com/, why: 'a request to Google Fonts' },
  { pattern: /mockServiceWorker/, why: 'the MSW service worker' },
  { pattern: /\bmsw\/(browser|node)\b|@mswjs\//, why: 'the MSW library' },
  {
    pattern: /createMockApi|setupWorker|HttpResponse\.json/,
    why: 'the mock API or the MSW worker',
  },
];

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else yield path;
  }
}

export function check(dir) {
  const problems = [];
  for (const file of walk(dir)) {
    if (/\.(woff2?|png|jpe?g|ico|webp|avif)$/.test(file)) continue;
    const text = readFileSync(file, 'utf8');
    if (/mockServiceWorker\.js$/.test(file)) problems.push(`${file}: ${FORBIDDEN[1].why}`);
    for (const { pattern, why } of FORBIDDEN) {
      if (pattern.test(text)) problems.push(`${file}: ${why}`);
    }
  }
  return [...new Set(problems)];
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(import.meta.filename)) {
  const dir = resolve(process.argv[2] ?? 'out');
  const problems = check(dir);
  if (problems.length > 0) {
    console.error(`The build in ${dir} is not clean:\n${problems.map((p) => `  ${p}`).join('\n')}`);
    process.exit(1);
  }
  console.log(`${dir}: no Google Fonts request, no mock code.`);
}
