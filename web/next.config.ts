import type { NextConfig } from 'next';

// Static export (PRD 10.2, ui-core UI-STK-1). Pages are /, /scan and /grave; the scan and the package come from
// the query string, so there is no dynamic route and the host needs no rewrite (ui-core design 3).
const production = process.env.NODE_ENV === 'production';

if (production && process.env.NEXT_PUBLIC_API_URL === undefined) {
  throw new Error(
    'NEXT_PUBLIC_API_URL is not set. Set it to the API origin (an empty string means same origin).',
  );
}

const mocking = process.env.NEXT_PUBLIC_API_MOCKING === 'enabled';

const config: NextConfig = {
  output: 'export',
  trailingSlash: false,
  images: { unoptimized: true },
  reactStrictMode: true,
  poweredByHeader: false,
  // The mock API is bundled by the test build only (npm run build:e2e). Every other build resolves `@/mocks/browser` to an
  // empty stub, so neither `msw` nor the handlers can reach the production output (ui-core UI-STK-8). In the test
  // build, `msw/browser` has a `node: null` export condition that fails when the server render of a client component is
  // compiled, so it is pointed at the file.
  turbopack: {
    resolveAlias: mocking
      ? { 'msw/browser': './node_modules/msw/lib/browser/index.js' }
      : { '@/mocks/browser': './mocks/browser-stub.ts' },
  },
};

export default config;
