# Graveyard web

The static site: landing page, exhumation progress, graveyard scene, Lights On table and death certificate. Spec: `.kiro/specs/ui-core/`. Design rules: `.kiro/steering/frontend-design.md`.

Next.js 16 static export (`output: 'export'`), TypeScript, Tailwind 4, Framer Motion. No server code. Dependencies are pinned exactly and `package-lock.json` is committed; use `npm ci`, not `npm install`. Node version: `.node-version`.

## Scripts

Run from `web/`.

| Command                                     | What it does                                                                                                                    |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `npm run dev`                               | Dev server on `http://localhost:5173` (the origin the dev API allows through CORS).                                             |
| `npm run build`                             | Production static export into `out/`. Needs `NEXT_PUBLIC_API_URL`.                                                              |
| `npm run check:build`                       | Fails if `out/` has a Google Fonts request or any mock-API code.                                                                |
| `npm run lint`, `format:check`, `typecheck` | ESLint, Prettier, `tsc --noEmit`.                                                                                               |
| `npm test`                                  | Vitest (jsdom, MSW in node). Includes the axe checks and the art fidelity tests.                                                |
| `npm run gen:api`                           | Regenerates `lib/api/schema.d.ts` from `backend/api/openapi.yaml`. CI fails if the file differs.                                |
| `npm run lhci`                              | Lighthouse on `out/index.html` (3 runs, performance median at least 0.9). Run after `npm run build`.                            |
| `npm run build:e2e`                         | A build with the mock API compiled in, for the browser tests. Overwrites `out/`.                                                |
| `npm run e2e`                               | Playwright smoke test against `out/` (serve on port 4173). Run after `build:e2e`. Needs `npx playwright install chromium` once. |

`content/evidence.generated.json` is written from `eval/heldout/results.v2.json` by `npm run gen:evidence`, which every dev, build, lint, test and typecheck script runs first. It is git-ignored.

## Environment

| Variable                  | Meaning                                                                                                                                                                           |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL`     | API origin, for example `https://<api-id>.execute-api.eu-west-2.amazonaws.com`. Public, not a secret. Empty means same origin. Copy `.env.example` to `.env.local` (git-ignored). |
| `NEXT_PUBLIC_API_MOCKING` | `enabled` compiles the mock service worker in. Used only by `build:e2e`. Never set it for a deployed build.                                                                       |

## Routes

Query-string routes, so the export needs no per-scan files:

- `/` landing
- `/scan?id=<scanId>` exhumation progress, then the graveyard scene and Lights On table
- `/grave?scan=<scanId>&purl=<encoded purl>` death certificate

View state (Lights On, filters, sort) is kept in the URL, with `localStorage` key `graveyard.view` as a fallback.

## Host contract (for infra-edge)

1. Serve the files in `out/`.
2. Map an extensionless path to its `.html` file (`/scan` to `scan.html`, `/grave` to `grave.html`). `serve` does this by default. CloudFront needs the usual clean-URL function.
3. Answer unknown paths with `404.html` and status 404.
4. Allow the API origin in the Content-Security-Policy `connect-src`. Fonts are self-hosted, so no other external origin is needed.

There are no per-scan rewrites and no dynamic segments.

## Mock API and fixtures

- `content/haunted-house/` holds the committed capture of a real scan of `olajaido/haunted-house` (same bytes as `design/fixtures/haunted-house/`; a test checks they match). Tests and the mock API read it.
- `mocks/handlers.ts` is the MSW handler set used by the Vitest suite. `mocks/browser.ts` is the scripted world used by the browser test. The production build aliases it to `mocks/browser-stub.ts`, and `check:build` enforces that nothing from MSW ships.
- Where the API has no value, the UI shows "Not recorded". It does not invent one.

## Checking a dependency before adding it

From `backend/`: `uv run python -m cli autopsy --all --purl pkg:npm/<name>@<version>`. Record the verdict in `.kiro/specs/ui-core/design.md` section 10.
