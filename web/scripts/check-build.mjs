// Checks the production export (ui-core UI-STK-4 and UI-STK-8): it must not talk to Google Fonts, and it must hold no
// mock code. It also guards the Content-Security-Policy of the host (infra-edge EDGE-HDR-2, design 7.2): the policy allows
// inline scripts only because the Next.js export writes three known ones into every page, and it allows no inline style at all
// (no style-src-attr exception), so any other inline script, <style> element, style attribute, event handler or javascript: URL
// fails here and not in a browser.
// Run after `npm run build`. Exit code 1 with the offending files when a check fails.
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

// The three inline scripts of every page of the static export: the Turbopack chunk registry, the flight data initialiser and
// the flight data payload.
const KNOWN_INLINE_SCRIPTS = [
  /^\(globalThis\["TURBOPACK"\]/,
  /^\(self\.__next_f\s*=\s*self\.__next_f\s*\|\|\s*\[\]\)\.push\(\[0\]\)$/,
  /^self\.__next_f\.push\(/,
];
export function cspProblems(html) {
  const problems = [];
  for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
    if (/\bsrc\s*=/.test(match[1])) continue;
    const body = match[2].trim();
    if (!KNOWN_INLINE_SCRIPTS.some((known) => known.test(body))) {
      problems.push(
        `an inline script that is not one of the three Next.js shapes: ${body.slice(0, 40)}`,
      );
    }
  }
  const markup = html.replace(/<script\b[\s\S]*?<\/script>/g, '');
  if (/<style\b/i.test(markup)) problems.push('a <style> element (the CSP has no inline style)');
  for (const [tag] of markup.matchAll(/<[a-zA-Z][^>]*>/g)) {
    if (/\sstyle\s*=/i.test(tag)) problems.push('a style attribute (the CSP has no inline style)');
    if (/\son[a-z]+\s*=/i.test(tag)) problems.push('an inline event handler attribute');
    if (/javascript:/i.test(tag)) problems.push('a javascript: URL');
  }
  return [...new Set(problems)];
}
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
    if (/\.html$/.test(file)) for (const why of cspProblems(text)) problems.push(`${file}: ${why}`);
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
  console.log(`${dir}: no Google Fonts request, no mock code, nothing the CSP would block.`);
}
