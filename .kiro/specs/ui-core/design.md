# Design: ui-core (LEAN)
> Implements `requirements.md` (revision 2). Design system: `.kiro/steering/frontend-design.md`. API contract: `backend/api/openapi.yaml`, updated by group B. Status: REVISION 2 for review, 23 Nov 2026.

## 1. Decisions
Resolved by the maintainer on 23 Nov 2026 (the original D1 to D14, with the changes below):
| # | Decision | Outcome |
|---|----------|---------|
| D1 | Framework and routes | Next.js static export. Routes are static pages with query strings: `/scan?id=<scanId>` and `/grave?scan=<scanId>&purl=<encoded purl>`. No dynamic segment, no placeholder page, no host rewrite, **no routing gate**. Pretty URLs may come later via `infra-edge`. `NEXT_PUBLIC_API_URL` replaces `VITE_API_URL`. |
| D2 | Package manager | npm, `package-lock.json`. |
| D3 | Resting stones | Drawn, with a Resting chip (mockup), plus "Resting: N" in the header. |
| D4 | Cursed and Wounded | PRD definitions: overlays on any state; both true shows Cursed. |
| D5 | Dead | The product runs model v2, so Dead is declared-only and Ailing absorbs what v1 called Dead by score. A PRD amendment records it (UI-DOC-1, task T2), and the landing copy is written for v2. |
| D6 | Landing example | Committed fixtures (scans expire by TTL): `design/fixtures/haunted-house/{scan,graves,grave-lodash.template}.json`, copied verbatim to `web/content/haunted-house/`. |
| D7 | Dropped from the Exhumation mockup | Per-state tally, "Fresh toe tags", "68% deep". Kept and now real: lantern path, "N of M examined" (B2), "N lockfiles dug up" and "N plots found" (B3), elapsed time, dig depth. |
| D8 | Certificate aside | "Last rites" and "Perform the rites" omitted. "Buried alongside" is not drawn (the API has no data for it). |
| D9 | Evidence links | Built by the server (B6), not the UI. |
| D10 | Wax seal for other states | State word and state ink (proposal, approved). |
| D11 | 360 px deviations | Fluid gutter and h1 sizes (approved). |
| D12 | CI | One `web` job (approved). |
| D13 | `ui-theme.md` | Replaced by a one-line pointer; surviving rules carried into `frontend-design.md` section 10. **Done.** |
| D14 | Env var | `NEXT_PUBLIC_API_URL`; dev URL only in git-ignored `.env.local`. |
New in this revision, for you to confirm when you review:
| # | Choice | Reason |
|---|--------|--------|
| N1 | **The progress counter is written by the state machine**, with DynamoDB service integrations (`dynamodb:updateItem` states), not by the autopsy Lambda. | `security.md` gives the `autopsy` role only `GetItem` and `PutItem`. The state machine role already has `dynamodb:UpdateItem` on the table (for `MarkFailed`), so no IAM change, no steering change, and the autopsy Lambda is untouched. Alternative: add `UpdateItem` to the autopsy role. |
| N2 | `services` has **one entry per service id**: `{id, manifests: [{ecosystem, path}]}`, so a directory with two lockfiles is one entry with two manifests. No duplicate `id`. | Maintainer decision (review of N1 to N5). |
| N3 | B6 is read as: the **server** adds link-outs (`evidenceLinks`) to human pages on fixed hosts, and the UI shows evidence kind plus those links, never any text from the source. The raw `source_url` fields (API endpoints) stay in the payload and are not shown. | "Read the notice on npmjs.com" needs a page URL, which the API does not hold today. |
| N4 | `progress` is non-null only while the stage is `AUTOPSY`. | As you specified. |
| N5 | The MSW fixtures are the real captures plus a typed overlay for the fields group B adds. The overlay sets `via` for only the seven packages whose introducer is known (the mockup list; `lodash.template` from its real path) and leaves the rest `null`. A transitive package with `via: null` is a valid API outcome (no path kept), and the UI renders "transitive". | After group B is deployed to dev, the maintainer recaptures `design/fixtures/haunted-house/` from a fresh dev scan and the overlay is removed (M1, mandatory). |
| N6 | **Path node states** come from the graves list the page already holds. A node in the list gets a state badge, and a node not in it gets none. No backend change. | Maintainer decision. |

## 2. Structure
```
web/
├── app/                        # thin Next layer
│   ├── layout.tsx  fonts.ts  globals.css (tokens, @theme)  page.tsx  not-found.tsx
│   ├── scan/    page.tsx  layout.tsx     # layout holds the Framer Motion provider
│   └── grave/   page.tsx  layout.tsx
├── components/
│   ├── art/        night-scene, moon, fog, fence, dead-tree, chapel, plot-backdrop, grave (scene size), grave-icon (legend size),
│   │               lantern, open-grave-scene, wax-seal, toe-tag, step-art (4), brand-mark
│   ├── layout/     site-header, site-footer (fence), skip-link, page-shell, app-link
│   ├── ui/         button, chip, pill, status-region, copy-link-button, error-view, not-found-view
│   ├── landing/    hero, repo-form, example-strip, how-it-works, six-states, evidence-stone
│   ├── exhumation/ exhumation-page, lantern-path, elapsed
│   ├── graveyard/  results-page, summary, filter-chips, view-toggle, plot, stone, dig-first, empty-state
│   ├── table/      lights-on-table, sort-header, use-window-rows
│   └── certificate/ certificate-page, fields, descent, evidence-list, evidence-notes, buried-alongside
├── lib/
│   ├── api/    schema.d.ts (generated), client.ts, errors.ts, cache.ts
│   ├── model/  purl, grave (display state), buckets, plots, cause, filter-sort, stage-map, poll, repo-input, route, url-state, dates, links, signals
│   ├── hooks/  use-resource, use-scan-poll, use-query-state, use-roving
│   └── contrast.ts (+ test)
├── content/haunted-house/   scan.json, graves.json, grave-lodash.template.json   # verbatim copies of design/fixtures/haunted-house/
├── content/evidence.generated.json                                              # git-ignored, written by scripts/gen-evidence.mjs
├── mocks/      handlers.ts, scenario.ts, fixtures/ (overlay + builders), browser.ts, node.ts
├── e2e/        smoke.spec.ts
├── scripts/    gen-evidence.mjs, check-build.mjs, e2e-build.mjs
├── lighthouserc.json  playwright.config.ts  vitest.config.ts  eslint.config.mjs  prettier.config.mjs
├── next.config.ts  postcss.config.mjs  tsconfig.json  .env.example  .node-version  package.json  package-lock.json  README.md
```
Tests sit beside the code as `*.test.ts(x)`. Kebab-case files, PascalCase components (`structure.md`). `components/` and `lib/` use `next/*` only through `app-link.tsx` and `lib/model/route.ts`.

## 3. Routing and static export
`next.config.ts`: `output: 'export'`, `trailingSlash: false`, `images: { unoptimized: true }`. The build writes `index.html`, `scan.html`, `grave.html` and `404.html`. There are no dynamic segments.

**Query contract** (`lib/model/route.ts`, pure, unit tested):
| Page | URL | Parameters |
|---|---|---|
| Landing | `/` | none |
| Scan | `/scan?id=<scanId>[&view=scene\|table][&state=…][&service=…][&sort=…][&dir=…]` | `id` required, must match the scan ID pattern |
| Grave | `/grave?scan=<scanId>&purl=<encodeURIComponent(purl)>` | both required, `purl` starts with `pkg:` |
`scanHref(id, view?)` and `graveHref(scanId, purl)` build the URLs with `URLSearchParams`; `parseQuery(search)` returns `{ ok: true, … } | { ok: false }`. Values decode once, so a scoped purl round-trips: `pkg:npm/%40babel/core@7.0.0` becomes `pkg%3Anpm%2F%2540babel%2Fcore%407.0.0` in the URL and back. The API path for the same purl uses `encodeURIComponent` again (section 4.1).

**Reading the query.** `useQueryState()` reads `location.search` in an effect after mount (the exported HTML is the same for every link), listens to `popstate`, and writes view state with `history.replaceState`. `useSearchParams` is not used (a static export needs a Suspense boundary for it). Until mounted, pages render the loading state.

**Navigation.** Links go through `AppLink` (`next/link`); after the POST the form calls `router.push(scanHref(id))`. Both targets are real static pages, so client navigation needs no special handling.

**Host contract** (written into `web/README.md`, UI-RT-4): serve the files in `out/`; map an extensionless path to its `.html` (`/scan` to `scan.html`; `serve` does this by default and CloudFront needs the usual clean-URL function); `404.html` for unknown paths with status 404; allow the API origin in `connect-src`. Nothing else, and no per-scan rewrite.

**Titles and focus** (UI-RT-5): `usePageTitle(title)` sets `document.title`; `useFocusHeading()` focuses the `<h1 tabIndex={-1}>` once data is ready.

**404.** `app/not-found.tsx` renders `NotFoundView` for unknown paths. An unresolvable query, an unknown scan or an unknown grave renders the same view in place, with copy that says what was not found.

## 4. Data and model
### 4.1 API client (`lib/api/client.ts`)
- `createClient({ baseUrl, fetch })` returns `createScan(repo)`, `getScan(id)`, `listGraves(id)`, `getGrave(id, purl)`. Return types are the generated types (`components['schemas'][…]`).
- URL: `${baseUrl}/v1/scans/${encodeURIComponent(id)}` and `/graves/${encodeURIComponent(purl)}` (a purl with `%40` becomes `%2540`; the handler decodes once, `api/routes.py` `_purl_from_path`). `AbortController` timeout 15 s. `credentials: 'omit'`. The only request header is `content-type: application/json` on POST, which is why CORS allows it.
- `listGraves` loops `limit=200` and the returned `nextCursor` (unchanged) to the end, up to 20 pages, and returns `{ total, items }`. A cap hit becomes a `parse` error, not a silent truncation.
- Errors: one `ApiError { kind: 'problem'|'network'|'timeout'|'parse', status?, detail? }`. A problem body is accepted only with the four RFC 9457 fields.
- Cache (`cache.ts`): a `Map` keyed by URL, filled only for `COMPLETE` scans and their graves; cleared on reload.
- No `guards.ts`: after B5 the types cover every field. The one narrowing helper is `formatEvidenceValue(value: unknown)` in `model/signals.ts`, which turns an evidence `value` (any JSON) into text or "not recorded".

### 4.2 Purl display (`model/purl.ts`)
`parseDisplayPurl('pkg:npm/%40babel/core@7.0.0') -> { type:'npm', ecosystemLabel:'npm', namespace:'@babel', name:'core', fullName:'@babel/core', version:'7.0.0' }`. Display only: drops qualifiers, never throws (an unparsable purl is shown whole). The server validates purls. `via` and path nodes (`npm/gulp-util@3.0.8`, a package key) parse through the same function with a `pkg:` prefix.

### 4.3 Display state (`model/grave.ts`)
`displayOf(grave) -> { type: 'cursed'|'dead'|'ailing'|'resting'|'wounded'|'alive'|'unknown', base, overlays, label, words }` per `frontend-design.md` section 5. `label`: `dead · cursed`, `alive · wounded`. `words`: `Dead and cursed`. Type precedence: cursed, dead or ailing, wounded, resting or alive; anything unrecognised is `unknown` (no stone). Severity rank for sorting: cursed 0, dead 1, ailing 2, resting 3, wounded 4, alive 5, unknown 6.
Relationship text (`relationOf(grave)`): `direct` when `direct`; `via <name>` when `via` is set; otherwise `transitive`.

### 4.4 Size buckets (`model/buckets.ts`)
Input: all graves of the scan. Sort by `priority` descending (null last), then purl. With `N` graves, a grave at 0-based rank `r` gets bucket `min(3, floor(4r / N))`. Equal priorities take the bucket of the first of the tie. Null priority is bucket 3. Widths `[150, 124, 104, 86]`, height `w × 160 / 120`, column width `w + 16`. The real fixture has many ties (a priority of 90.0 for nine packages), which the tie rule keeps in one bucket. Example: 7 graves give buckets 0,0,1,1,2,2,3. The accessible name's "priority N of M" uses the 1-based position in the same list.

### 4.5 Cause text (`model/cause.ts`)
Table cause (from `state`, `deadReason`, `cursed`, `wounded` only):
| Input | Text |
|---|---|
| dead, declared | Declared dead by its source |
| dead, score (only a stored v1 scan) | High abandonment score |
| ailing | Signs of neglect |
| resting | Finished and stable |
| cursed | Known vulnerability, no fix available |
| wounded | Upgrade advised |
Texts join with "; ". Alive and unknown give nothing. The certificate's "Cause of death" extends the table with one sentence about the largest non-null `contributions` entry ("Mainly: release staleness (r2)", with the PRD §7.1 names) and, for `declared`, "its source reports it as deprecated, archived or retired". It never says which, because the payload does not say. This template is replaced by the narrative when `narrate` ships.

### 4.6 Plots (`model/plots.ts`)
Map `scan.services` (one entry per `id`) to plots `{ id, ecosystems, manifests }`, where `ecosystems` are the distinct `manifests[].ecosystem` and `manifests` the lockfile names (last path segment); attach each grave to every plot whose `id` is in its `services`. A grave whose service is missing from the list adds a derived plot; a null `services` (pre-B scan) derives all plots from the graves and has no manifests. Per plot: `title` (`"."` gives "The root plot", otherwise "The `<last path segment>` plot"), `subtitle` (`service "<id>" · npm · package-lock.json`), `stones` (priority order, first 40), `hidden` (the rest), `clean` (no graves at all, shows "Nothing buried here. This plot is clean."). Order: highest priority first, then `id`. Stone key: `id + purl`.

### 4.7 View and filter state (`hooks/use-query-state.ts`)
`view=scene|table`, `state=dead|cursed|ailing|resting|wounded`, `service=<id>`, `sort=priority|package|state`, `dir=asc|desc`, in the page's query string. The view also persists in `localStorage` (`graveyard.view`), used only when the URL has no `view`. Chip semantics: one active chip at a time. `dead|ailing|resting` match the base state, `cursed` and `wounded` match the overlay, so a dead and cursed package matches both. Chip counts come from `counts` and "All" shows the number of graves.

## 5. Components
### 5.1 Art (`components/art/`)
Ported from the mockups with coordinates, shapes and colours unchanged (hex replaced by token variables only where a token exists). Every component takes `className`, is `aria-hidden`, and uses `useId()` for pattern IDs.
| Component | Source |
|---|---|
| `NightScene` | Main hero SVG: stars, moon and halo, far hill, chapel, near hill, picket fence, background stones, dead tree, foreground hill, cursed glow, five foreground graves with names, two fog layers. The names in it are illustration, not data |
| `Moon`, `Fog`, `Fence`, `DeadTree`, `Chapel` | pieces of the above, reused by the progress and results headers |
| `PlotBackdrop` | per-plot hills, fence and ground (`viewBox 0 0 1200 260`) |
| `Grave` | the five scene graves (`viewBox 0 0 120 160`): cursed, dead, ailing, resting, wounded. `alive` is the wounded sapling without the bandage rectangle (the scene draws no alive grave) |
| `GraveIcon` | the six 80×90 legend graves of "Six states" |
| `Lantern` | three variants (lit, working with animated flame, unlit), `64×90` |
| `OpenGraveScene` | the Exhumation scene with the dig animation, and a `depth` prop (5.3). The mockup's `role="img"` label and "68% deep" text are dropped |
| `WaxSeal` | `96×96`, word and date as props |
| `ToeTag` | the parchment tag with ring and string, as a link container |
| `StepArt` | the four "how it works" illustrations |
| `BrandMark` | the 28×32 gravestone mark |

### 5.2 Landing
`Hero` (NightScene, header nav, h1 with italic accent, lead, `RepoForm`), `ExampleStrip`, `HowItWorks`, `SixStates`, `EvidenceStone`, `SiteFooter`.
- `ExampleStrip` imports `content/haunted-house/scan.json` (`counts.total`, `counts.dead`, `counts.cursed`, `counts.ailing`, `source.repo`, `updatedAt`). The mockup's "exhumed in about a minute" becomes the real duration `updatedAt - createdAt` (32 s in the capture): "exhumed in 32 seconds".
- `SixStates` copy, written for model v2: Alive "Maintained and growing. Nothing to do." Resting "Finished, not abandoned. Quiet because it is done." Ailing "Cracks are showing. Worth watching." Dead "Declared dead on evidence: deprecated, archived or retired by its maintainer." Cursed "A known vulnerability with no fix. Dig these up first." Wounded "A fixable vulnerability, or an upgrade is advised. Upgrade, do not replace." Each with the plain term ("Dead (abandoned)").
- `EvidenceStone`: reads `evidence.generated.json` (section 9).
- `RepoForm`: controlled input; `normaliseRepo(text)` returns `{ ok: true, repo } | { ok: false }`. It accepts `owner/name`, `github.com/owner/name`, `http(s)://github.com/owner/name`, with an optional `.git` or trailing slash. It checks owner `^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$`, name `^[A-Za-z0-9._-]{1,100}$` (not `.` or `..`), exactly one `/`, mirroring `exhume/validate.py`. States: idle, submitting ("Digging…", disabled, `aria-busy`), error (`<p id="repo-error">`, `aria-invalid`, `aria-describedby`, focus on the input).
- The landing imports no Framer Motion and no API client code beyond the form.

### 5.3 Progress (`exhumation/`)
`ExhumationPage` uses `useScanPoll(scanId)` and renders the header (elapsed time since `createdAt`, repo from `scan.source.repo`, "N plots found" from the distinct `services[].id` once known, "Copy link to this scan"), `OpenGraveScene`, `LanternPath` and the `StatusRegion`. On `COMPLETE` it renders `ResultsPage` in place; on `FAILED` it renders `ErrorView`.
- **Captions** (facts only): Validate "public repository"; Exhume "N lockfiles dug up" (the sum of `manifests.length`, once known); Identify "package inventory"; Trace roots "who brought whom"; Autopsy "N of M examined" (`progress`); Pronounce "final states".
- **Dig depth.** `depth = (doneLanterns + (stage is AUTOPSY && progress ? examined/total : 0)) / 6`, clamped to [0, 1], 1 when complete. `OpenGraveScene` draws a backfill rectangle (earth colour `#2A2219`) over the pit, from `y = 262 + 140·depth` down to `402` (pit is `610..840` wide), added on top of the unchanged mockup shapes, so the pit opens and the coffin shows as the autopsy finishes. Motion-safe CSS transition on its height. The scene stays decorative; the number is in the text.

### 5.4 Results (`graveyard/`, `table/`)
`ResultsPage(scanId)` loads the scan and all graves with `useResource`, then renders the header band (`Summary`), the chips and view toggle, then `Plot`s or `LightsOnTable`.
- **Summary sentence:** `"{total} dependencies dug up across {n} plots. {dead} dead, {cursed} cursed, {ailing} ailing."` Zero counts are dropped. `n` is the number of plots drawn.
- **DigFirst:** five `ToeTag` links; each shows `name@version`, the state label, and `direct` or `via <name>` or `transitive`.
- **Plot:** `<section aria-labelledby>` with the backdrop, title, subtitle, a `role="group"` of stones, the "N more in Lights on" link, and the clean-plot message. Entrance fade with Framer Motion (`LazyMotion`, `domAnimation`).
- **Stone:** an `<a>` containing the `Grave`, the name (mono 12, `overflow-wrap: anywhere`) and a meta line `3.6.2 · dev · via gulp-util` in the state's bright colour on `plot`. Hover and focus lift 6 px.
- **Roving tabindex** (`use-roving`): the group keeps `activeIndex`; the active stone has `tabIndex 0`; ArrowLeft/Right move by one, ArrowUp/Down to the stone nearest in the row above or below by bounding box, Home and End jump; a click sets the active index.
- **Empty** when `total === 0`. **Partial:** the fog banner of UI-GY-1.

### 5.5 Lights On table
`<div role="region" aria-label="Register of graves" tabIndex={0} class="overflow-x-auto">` containing `<table>` with `<caption>`, `<thead>` with sort buttons (`<th scope="col" aria-sort>`), and `<tbody>` rows (`<th scope="row">` holds the package link). The comparator is stable and falls back to purl. Default: priority descending.
Windowing (`use-window-rows`) starts at 501 rows: fixed row height 49 px, visible range plus 10 rows of overscan from `scrollTop`, spacer `<tr>` above and below, `aria-rowcount` on the table and `aria-rowindex` on every rendered row, region `max-height: 70vh`. Below 501 rows nothing is windowed, so Tab order and Find in page cover every row.

### 5.6 Certificate (`certificate/`)
`CertificatePage` loads the grave and the scan (for the repo name) in parallel. Layout as the mockup: a parchment `article` and an aside.
| Block | Source |
|---|---|
| Header (seal icon, "Registry of the Graveyard", h1, "issued on the evidence, {asOf}") | `asOf` |
| Fields | purl (name, version), `state`/`deadReason`, `cursed`/`wounded`, cause (4.5), ecosystem (purl type), place of rest (`services`, `scope`), `mortality`, `confidence`, `priority` (1 decimal) |
| Line of descent | `examplePaths`, `via`, `pathCount` |
| Evidence on file | `evidence` (11 signal keys), `signals.s7_advisories`, `evidenceLinks` |
| Notes on the evidence | `warnings` |
| Footer | `scanId` from the query, `modelVersion`, "— the Coroner", `WaxSeal` |
| Aside | None. "Buried alongside" is not drawn until the API returns reverse dependencies; the certificate is a single centred column (max 880 px). |
**Evidence rows.** One row per signal key in the order S1, S1b, S2, S3, S4, S5, S6 open, S6 closed, S7, S8, S9. A row shows the plain name and the evidence kind (fixed copy in `model/signals.ts`: S1 "Declared dead", S1b "This version deprecated", S2 "Latest release", S3 "Last push", S4 "Maintenance activity (Scorecard)", S5 "Committers, 12 months", S6 "Issues", S7 "Known vulnerabilities", S8 "Scorecard overall", S9 "Weekly downloads"), the value from `formatEvidenceValue`, the fetch time, the `note`, and the links whose `signals` include the key. Link text is built from `kind`, the host and whether the covered signal is true: `registry` with S1 or S1b true gives "Read the notice on npmjs.com" (or "…on pypi.org"); otherwise "View on npmjs.com". `repository` gives "See the repository on github.com", `advisory` "Read the advisory on osv.dev", `deps_dev` "See the scores on deps.dev". `safeLink(url)` renders a link only for `https:` on `www.npmjs.com`, `pypi.org`, `github.com`, `osv.dev` or `deps.dev`, as defence in depth. No text from a source is shown, and a signal without a value shows "not recorded" and its `note`.
**Descent.** Root node is the `service` (shown as the repo name when the service is "."). Nodes are package keys, displayed as `name@version`. The last node is highlighted (`paper-tint`). Each node found in the graves list (`useResource` on `listGraves`, cached when the user came from the results page, fetched in the background otherwise) gets a state pill (`dead`, `dead · cursed`, …); a node not in the list gets none, and the page makes no request for it. Until the list loads there are no badges. Sentence: direct gives "You chose this package yourself."; otherwise "It arrived with `<via>`." plus "{pathCount} paths lead here, showing {k}." when they differ.

## 6. Progress details
### 6.1 Polling (`use-scan-poll.ts`, pure schedule in `model/poll.ts`)
`nextDelay(prev) = min(5000, round(prev × 1.5))`, first delay 1500, reset when `stage` changes. State: `{ phase: 'loading'|'running'|'complete'|'failed'|'notfound'|'lost', scan?, failures }`. A timer re-arms after each response (no overlap). `visibilitychange` clears the timer while hidden and polls at once when visible. Transport failures retry up to 5 times in a row, then `lost`. Unmount cancels the timer and aborts the request. A scan already `COMPLETE` or `FAILED` is read once. Elapsed time: `max(0, now - Date.parse(createdAt))`, ticked each second outside the live region.

### 6.2 Stage map (`model/stage-map.ts`)
One lantern works at a time once group B is deployed.
| `status` / `stage` | Done | Working | Status text |
|---|---|---|---|
| QUEUED | none | none | "Waiting for a gravedigger" |
| RUNNING, `VALIDATE` | none | Validate | "Checking the plot" |
| RUNNING, `FETCH` | Validate | Exhume | "Digging up the lockfiles" |
| RUNNING, `SBOM` | Validate, Exhume | Identify | "Tagging the bodies" |
| RUNNING, `GRAPH` | …, Identify | Trace roots | "Tracing the roots" |
| RUNNING, `AUTOPSY` | …, Trace roots | Autopsy | "Examining the bodies" |
| RUNNING, `CLASSIFY` | …, Autopsy | Pronounce | "Pronouncing" |
| COMPLETE (`DONE`) | all | none | "Exhumation complete" |
| FAILED | those before the stage's lantern | none; the stage's lantern is marked "stopped" | the error title |
| any other stage | unchanged | unchanged | "Working…" |
The word ("done", "working", "waiting", "stopped") is text beside each lantern, not colour only.

## 7. Error copy (`lib/api/errors.ts`)
One table typed `Record<ErrorCode, …>` with `ErrorCode = components['schemas']['Scan']['error']['code']` (from the enum, B4), so `tsc` fails when a code is added without copy. A Vitest test also reads the enum from `backend/api/openapi.yaml` with a regular expression and asserts both directions. Fields: `title`, `body`, `action` (`retry | edit | home`), `retryable`.
| Code or outcome | Title | Plain sentence | Action |
|---|---|---|---|
| `INVALID_INPUT`, POST 400 | That is not a grave site | Enter a public GitHub repository as owner/name, for example `olajaido/haunted-house`. | edit |
| `REPO_NOT_FOUND` | No such plot | We could not find that repository, or it is not public. Check the spelling. Private repositories are not supported. | edit |
| `NO_MANIFESTS` | Nothing buried here | No lockfile we can read was found. We read `package-lock.json`, `uv.lock`, `poetry.lock` and `requirements*.txt`. | edit |
| `TOO_LARGE` | Too heavy to lift | This repository's lockfiles are larger than a scan accepts. | home |
| `TREE_TRUNCATED` | The cemetery is too big to map | GitHub returned a partial file list for this repository, so we cannot find every lockfile. | home |
| `TOO_MANY_PACKAGES` | Too many bodies | This repository has more packages than one scan accepts. | home |
| `GITHUB_RATE_LIMITED` | GitHub asked us to slow down | GitHub is limiting requests right now. Try again in a few minutes. | retry |
| `GITHUB_AUTH_FAILED` | The gate is locked | Graveyard could not sign in to GitHub. This is on our side. Try again later. | retry |
| `SBOM_FAILED`, `SBOM_INVALID` | The tags would not read | We could not build a usable package list from the lockfiles. | home |
| `TIMEOUT` | The dig took too long | The scan ran past its time limit and was stopped. Try again. | retry |
| `INTERNAL`, other 5xx | Something went wrong underground | The scan failed because of an internal error. Try again. | retry |
| POST 413 | That request was too big | Send only an owner/name. | edit |
| POST 429 | Too many digs at once | Wait a minute, then try again. | retry |
| POST 503 | The crypt is resting | New scans are paused. Scans that already finished stay readable. | home |
| GET 404, unresolvable link | This plot is not on the map | Scans are kept for 30 days, and the link may be mistyped. | home |
| GET 400 (certificate) | That grave marker is not valid | The package link is not well formed. | back |
| network, timeout | The path is out of reach | We could not reach the graveyard. Check your connection and try again. | retry |
| parse | Unreadable tags | The graveyard answered with something we could not read. | retry |
| unknown code | Something went wrong | the API's `error.title` | home |
The backend's own titles for `REPO_NOT_FOUND` and `NO_MANIFESTS` mention SBOM upload, which the UI does not have, so the UI uses its own text. A gateway 429 can arrive without CORS headers and look like a `network` error; that copy covers it. `Problem.type` is always `about:blank`, so POST errors are told apart by status.

## 8. Motion, accessibility and responsive notes
- Tokens are CSS variables from `globals.css`. Animations are Tailwind `@utility` classes defined inside `@media (prefers-reduced-motion: no-preference)`, plus the global `reduce` reset.
- `StatusRegion` renders `<div role="status" aria-live="polite" aria-atomic="true" class="sr-only">`; the text is set only on change.
- The skip link is the first element in `layout.tsx`, visible on focus, and targets `<main id="main" tabIndex={-1}>`.
- Focus ring: a `focus-ring` utility (`outline: 2px solid var(--focus); outline-offset: 3px`), `--focus` set to `bone` on dark roots and `ink` inside `.surface-paper`.
- Chips and view toggle are 44 px high. Stones are at most 166 px wide, so they wrap at 360 px. Plot padding is `clamp(16px, 5vw, 26px)`.
- No raster images: inline SVG and CSS only.
- Performance: fonts through `next/font/local` with preload for Cormorant 600 and Inter 400 only, `display: swap`; the hero SVG is inline and sized with `width` and `height`; below-the-fold sections use `content-visibility: auto` with `contain-intrinsic-size`; no client JS on the landing beyond the form and the nav.

## 9. Landing data
- `content/haunted-house/scan.json` is the capture of scan `01M82PBZE6AWAYGK3E37ZNXSNC-7ea402ccd4cd776b` (208 packages: 17 dead, 2 cursed, 84 ailing, 31 resting, 5 wounded, model v2, 22 Nov 2026, 32 s). A test compares `content/haunted-house/*` byte for byte with `design/fixtures/haunted-house/*`.
- `scripts/gen-evidence.mjs` runs before `dev` and `build` (`predev`, `prebuild`), reads `eval/heldout/results.v2.json` and writes `content/evidence.generated.json` with `heldout.headline.dead_precision.proportion` (`num`, `den`, `value`), `views.reviewed.dead_precision_wilson`, `gate.passed`, `heldout.floors` and `as_of`. It exits non-zero if a field is missing. The stone shows "N/D correctly pronounced dead", "95% interval a – b" and, when `gate.passed` is false, "The sample was small, so the formal verdict is inconclusive". Today: 10/10, 0.722 to 1.000, `passed: false`.

## 10. Dependencies (exact pins, recorded at T3)
All 32 direct dependencies are pinned exactly (this table was checked at T3; eslint was re-checked when it moved to 9.39.5) (`.npmrc` `save-exact`, `package-lock.json` committed). Each was checked with the Graveyard CLI (`uv run python -m cli autopsy --all --purl pkg:npm/<name>@<version>` from `backend/`, the same engine as `autopsy_package`). Result: Dead 0, Ailing 0, Cursed 0, Wounded 1 (eslint, see below), Resting 4, Alive 27. The check ran without `GITHUB_TOKEN`, so GitHub signals are missing and confidence is lower (unverified).
| Package | Pin | Use | Autopsy |
|---|---|---|---|
| next, eslint-config-next | 16.4.6 | framework, lint (dev) | Alive |
| react, react-dom | 19.3.1 | UI | Alive |
| typescript | **5.9.3** | types (dev) | Alive. `typescript@7.0.2` was rejected: typescript-eslint peers `<6.1` and openapi-typescript peers `^5.x`. |
| tailwindcss, @tailwindcss/postcss, postcss | 4.3.5, 4.3.5, 8.5.33 | styling | Alive |
| framer-motion | 14.14.0 | entrances | Alive |
| @fontsource/cormorant-garamond, /inter, /jetbrains-mono | 5.3.0 | fonts (SIL OFL 1.1) | Alive |
| openapi-typescript | 7.13.0 | types from OpenAPI (dev) | Alive |
| vitest, vite, @vitejs/plugin-react, jsdom | 5.1.1, 8.3.8, 6.3.0, 31.0.1 | unit tests (dev) | Alive |
| @testing-library/react, /dom | 16.3.3, 10.4.2 | component tests (dev) | Resting |
| @testing-library/jest-dom, /user-event | 8.0.0, 14.6.13 | component tests (dev) | Alive |
| msw | 3.0.7 | API mocks (dev) | Alive |
| axe-core | 4.14.1 | a11y in Vitest (dev) | Alive |
| @playwright/test, @axe-core/playwright | 1.65.1, 4.14.0 | smoke (dev) | Alive |
| @lhci/cli | 0.16.1 | Lighthouse (dev) | Resting |
| serve | 14.2.8 | static server for tests (dev) | Resting |
| eslint | **9.39.5** | lint (dev) | Wounded (model v1: the registry marks every 9.x release deprecated, "no longer supported"; no advisory in OSV or deps.dev). `eslint@10.15.0` was rejected: the plugins of `eslint-config-next@16.4.6` (import, jsx-a11y, react) accept eslint up to 9, so 10 gave invalid peers and ERESOLVE. 9.39.5 is the `maintenance` tag. Revisit when `eslint-config-next` accepts 10. |
| prettier | 3.10.1 | format (dev) | Alive |
| @types/node, @types/react, @types/react-dom | 22.20.5, 19.3.0, 19.3.0 | types (dev) | Alive |
**Dev-only findings:** `eslint@9.39.5` is deprecated by the registry (above), so `npm ci` prints one `npm warn deprecated` line for it. It is not a peer or ERESOLVE problem, and `npm ls --all` reports none.
**Transitive finding:** `inflight@1.0.6` (declared Dead) is a dev-only transitive of `@lhci/cli` through `chrome-launcher`, `rimraf@3` and `glob@7`. It never reaches `out/`. Accepted; revisit when `@lhci/cli` drops `rimraf@3`.
**Not used:** `vitest-axe` (autopsy: Dead, last release 2022-10; axe-core is called through a 10-line helper), `@tanstack/react-virtual` (windowing is a small own hook), a YAML parser (the enum test uses a regular expression), any UI kit, state library, data-fetching library or schema validator.

## 11. Backend support, group B (one PR)
All work is in `backend/` and `infra/modules/workflow`, with tests, and `openapi.yaml` updated in the same PR. Checks: `uv run pytest -q`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy --strict core`, then `scripts/ci/local-checks.sh all`.
**IAM:** none. Every new write is a `dynamodb:updateItem` task of the state machine (role statement `TableUpdate` already exists, `infra/modules/workflow/main.tf` `sfn_statements`) or by an existing handler with `ddb_update` (`fetch`). The autopsy role stays at `GetItem`/`PutItem`/`BatchGetItem` (`security.md`). Nothing under `infra/bootstrap` or `github-oidc` changes.

### B1 stages and B2 progress (`infra/modules/workflow/main.tf`)
New states, all `dynamodb:updateItem` service integrations like `MarkFailed`, key `SCAN#<scanId>` / `META`, `ConditionExpression attribute_exists(pk)`:
| State | Placement | Expression |
|---|---|---|
| `StageSbom` | `FetchManifests` → `StageSbom` → `GenerateSBOM` | `SET stage = :s, updatedAt = :u` with `:s = SBOM` |
| `StageAutopsy` | `BuildGraph` → `StageAutopsy` → `AutopsyMap` | `SET stage = :s, progressTotal = :t, progressExamined = :z, updatedAt = :u` with `:s = AUTOPSY`, `:t = {"N.$": "States.Format('{}', $.graph.total)"}`, `:z = 0` |
| `CountBatch` | in the Express child, `Autopsy` → `CountBatch` → `Counted` (a `Pass` with output `{counted: true}`) | `ADD progressExamined :n` with `:n = {"N.$": "States.Format('{}', States.MathAdd(States.MathAdd($.autopsy.ok, $.autopsy.cached), $.autopsy.failedCount))"}` |
- Both stage states have `ResultPath = null` and the same `Catch` to `HandleError` as their neighbours. `Autopsy` loses `End = true`, gains `Next = "CountBatch"` and `ResultPath = "$.autopsy"` (so `$.BatchInput.scanId` is still there for the key); its `ResultSelector` already returns `ok`, `cached` and `failedCount`, so the Lambda is unchanged and the batch size is `ok + cached + failed`. `Counted` replaces the child's output with a tiny object, so the `Items` list is never collected (SB-WF-3).
- `CountBatch` catches `States.ALL` and continues to `Counted` (a Succeed state): progress is best effort and must never fail a batch or a scan. The UI also clamps `examined` to `total`. A batch that fails for real never increments, so `examined` can stay below `total`; `CLASSIFY` replaces the progress anyway.
- Attribute names `progressTotal` and `progressExamined` avoid DynamoDB reserved words (`TOTAL`).
- API (`api/routes.py` `get_scan`): `progress = {"examined": min(int(e), int(t)), "total": int(t)}` only when `status` is `RUNNING`, `stage` is `AUTOPSY` and both attributes are numbers; else `null`. `stage` is returned as stored.
- Tests: `workflow.tftest.hcl` (states in order `Validate, FetchManifests, StageSbom, GenerateSBOM, BuildGraph, StageAutopsy, AutopsyMap, Classify, Finalise`; the two stage states and the child's `CountBatch` are `dynamodb:updateItem` on the table; stage states catch to `HandleError`; `CountBatch` does not; the expression strings above; the child still `DISTRIBUTED` and `EXPRESS`; the role gains no action); `api/tests` for `progress` (during `AUTOPSY`, other stages, missing attributes, `examined > total` clamped, old scan).

### B3 via and services
- `via`: `core/scan/records.py` gets `via_of(direct, example_paths)`. Direct gives `None`. Otherwise the first example path with at least two nodes gives `"pkg:" + nodes[-2]` (package keys are canonical purls without `pkg:`, `core/purl` `package_key`), else `None`. `build_node_record` stores `via`; `_SUMMARY` gains `"via"`; `get_grave` sets `via` to `None` for nodes stored before the change.
- `services`: `exhume/select.py` gets `ecosystem_of(name)` (`package-lock.json` is `npm`; `uv.lock`, `poetry.lock` and `requirements*.txt` are `pypi`). `workflow/fetch.py` stores `services=[{id: plan.path, manifests: [{ecosystem, path: file.path}, …]}, …]` (one entry per service, `id` unique, services sorted by `id`, manifests by name) on the scan item with `update_scan`, once the plans are selected. `get_scan` returns the list, or `null` for older scans. The `fetch` role already has `ddb_update`.
- Tests: `via_of` (direct, transitive, no path kept, scoped npm, two-node and longer paths), `ecosystem_of` for every lockfile name, fetch handler stores `services` (two directories; a directory with an npm and a PyPI lockfile gives one entry with two manifests; no duplicate `id`), `get_scan` and `get_graves` return the fields and `null` for old items.

### B4 error code enum
`Scan.error.code` in `openapi.yaml` becomes `enum` of the twelve codes. `api/tests` gains `test_openapi_error_codes_match_core`, comparing the enum with `core.scan.errors.CODES`. The UI test of section 7 is the other half.

### B5 schemas
`openapi.yaml` components, all with `required`:
- `Manifest {ecosystem: npm|pypi, path}`; `Service {id, manifests: [Manifest]}`; `Progress {examined, total}`; `Source {type: github, repo, ref?}`.
- `Scan`: `source: Source`, `stage: enum [QUEUED, VALIDATE, FETCH, SBOM, GRAPH, AUTOPSY, CLASSIFY, DONE] | null`, `services: [Service] | null`, `progress: Progress | null`, `error.code` enum.
- `GraveSummary`: required `purl, state, deadReason, cursed, wounded, mortality, confidence, priority, direct, scope, services, pathCount, via`; `state` enum `[alive, resting, ailing, dead, unknown]`.
- `Certificate` (allOf `GraveSummary` and): `exposure`, `exposureAssumed`, `servicesAffected`, `repo` (string or null), `examplePaths: [{service, nodes: [string]}]`, `signals` (the fields of `signals_to_json`, or null), `evidence` (an object with the eleven keys of `EVIDENCE_KEYS`, each `{value: any JSON, source_url, fetched_at, extra_source_urls, note}`, or null), `contributions` and `normalisedRisks` (maps of number or null), `warnings: [{code, source, signals, detail, status}]`, `evidenceLinks`, `asOf`, `modelVersion`.
- Contract test (`api/tests/test_contract.py`, no new dependency): a ~40-line recursive checker over the parsed YAML (`type`, `enum`, `required`, `properties`, `items`, `additionalProperties`, null unions, `$ref`, `allOf`) validates a real scan item, a graves page and a certificate built with `build_node_record`, for a scored node, an unscored node, a pre-B node and a minimal scan.
- Web: `npm run gen:api` regenerates `lib/api/schema.d.ts`; code that used the loose guards uses the generated types.

### B6 evidence links
`core/scan/links.py` (pure) exposes `evidence_links(purl, repo, advisory_ids) -> list[dict]`, called by `get_grave` at read time, so old nodes get links with no migration.
| `kind` | URL | `signals` it supports | Included when |
|---|---|---|---|
| `registry` | npm `https://www.npmjs.com/package/<name>/v/<version>`; PyPI `https://pypi.org/project/<name>/<version>/` | `s1b_version_deprecated`, `s2_latest_release_at`, `s9_weekly_downloads`, plus `s1_declared_death` for npm | always (purl parses) |
| `repository` | `https://github.com/<owner>/<name>` | `s1_declared_death`, `s3_last_push_at`, `s5_committers`, `s6_open_issues`, `s6_closed_issues` | `repo` is `github.com/<owner>/<name>` and passes `^github\.com/[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$` |
| `deps_dev` | `https://deps.dev/<npm\|pypi>/<name>/<version>` (name percent-encoded) | `s4_maintained`, `s8_overall` | always |
| `advisory` (one per ID) | `https://osv.dev/vulnerability/<id>` | `s7_advisories` | the ID passes `^[A-Za-z0-9._:-]{1,100}$` |
Links are built only from the components of the parsed purl (`core.purl.parse_purl`: type, namespace, name, version), the validated repo and the validated advisory IDs. Each component is percent-encoded with `urllib.parse.quote(..., safe='')` before it joins a constant `https://<host>/…` template; the host is never derived from input, and a final check asserts the result's host is in the allowlist and the scheme is `https`. The list is ordered `registry, repository, deps_dev, advisory…` and holds no text from any source. Tests: each kind for npm, scoped npm and PyPI; repo absent or malformed; hostile advisory IDs (`../`, spaces, `javascript:`) dropped; the host set equals the five allowed; **a crafted-input test**: purls whose name, namespace or version contain `/`, `@`, `\`, `#`, `?`, `%2f`, `//evil.example`, `@evil.example`, newlines and unicode, repos like `github.com/a/b@evil.example` and `evil.example/a/b`, and advisory IDs like `x@evil.example` or `//evil.example`, never give a URL whose parsed host is outside `{www.npmjs.com, pypi.org, github.com, osv.dev, deps.dev}` (a property test over generated strings with Hypothesis, plus the fixed cases).

### B7 compatibility, spec amendment, hand-off
- Every new field is present and `null` for items stored before the change (`services`, `progress`, `via`, and `evidenceLinks` is always computed). A test loads a pre-B scan item and node.
- `scan-backend` gets amendment A3 (requirements and design): SB-API-3 (`services`, `progress`, `stage` values), SB-API-4 and SB-API-5 (`via`, `evidenceLinks`, exact schemas), SB-WF-1 (the three new states), SB-ERR-1 (enum in the contract).
- `scripts/ci/guards.py` (route and Terraform lists) is unaffected: no route changes.
- Deploy: CI plans and applies on merge to `main`; the agent does not run Terraform or the AWS CLI. The captured fixtures predate B, which is why the web fixtures use an overlay (N5).

## 12. CORS, its own PR (`infra/modules/api`, `infra/envs/dev`)
Already in place: variable `cors_allowed_origins` (empty default, `*` rejected), a `cors_configuration` block with methods `GET`, `POST`, header `content-type`, `max_age 600`, wired through both env roots, and three module tests. The change:
1. `modules/api/main.tf`: `allow_methods = ["GET", "POST", "OPTIONS"]`. API Gateway answers the preflight itself once CORS is configured, so no route is added.
2. `modules/api/tests/api.tftest.hcl`: in `cors_origins_are_listed_when_given` assert the exact methods, `allow_headers == toset(["content-type"])`, `max_age == 600` and no `allow_credentials`. Keep the default-off and star-rejected runs.
3. `envs/dev/variables.tf`: `default = ["http://localhost:5173"]`, description "dev only". `envs/dev/tests/root.tftest.hcl`: a run asserting exactly that origin on `module.api.aws_apigatewayv2_api.http`. `envs/prod/tests/root.tftest.hcl`: a run asserting no CORS block.
4. Checks only through `scripts/ci/local-checks.sh` (fmt, validate, offline test, tflint, checkov).
**Bootstrap and apply role:** not changed. `UpdateApi` is `PATCH /apis/{id}`; the apply role's `ManageHttpApis` statement (`infra/modules/github-oidc/policies_apply_services.tf`) allows `apigateway:GET/POST/PUT/PATCH/DELETE` on `apis/*` under the `Project` and `Env` resource-tag condition, and the API carries those tags. `scan-backend` design §14 lists `UpdateApi` and `DeleteCorsConfiguration` for `aws_apigatewayv2_api`. Dev gets CORS when CI applies after the merge; until then the live dev API refuses calls from `localhost:5173` and development uses MSW.

## 13. API gaps after group B
| Gap | Status |
|-----|--------|
| Live progress, stage values | **Closed** by B1, B2. |
| Service list and manifest names, empty plots | **Closed** by B3. |
| Introducer ("via") of a transitive package | **Closed** by B3. When no path was kept, `via` is null and the UI says "transitive". |
| Error codes as an enum | **Closed** by B4. `Problem.type` is still `about:blank`, so POST errors are told apart by HTTP status. |
| Loose certificate schemas, undocumented fields | **Closed** by B5. |
| Human links for evidence | **Closed** by B6. Notice text and advisory titles are never recorded (SB-DATA-2). |
| State of each node on a dependency path | **Closed in the UI (N6):** badges come from the graves list; nodes not in it get none. No backend change. |
| Cause-of-death narrative | Deferred to `narrate` (Thu). The certificate uses the fixed template. |
| "Born" (first release), "Buried alongside" | Deferred to `rite-reincarnate` (Fri). Not drawn, not mentioned. Only the latest release date exists, shown as "Last released". |

## 14. Notes on the mockups
- The Graveyard mockup's table links take the bone focus ring on parchment (invisible); the UI uses the ink ring.
- The mockup table has no Priority column; it is added because sorting by priority is required. The default order is priority.
- Mockup stone sizes follow "cursed, then direct, then transitive". The UI uses priority buckets, which rank cursed first through the 1.5 multiplier in the score.
- The mockup's "Validate: public repo, main" caption assumed `main`; the UI says "public repository" because the scan may use another default branch.
- Landing and certificate headers differ in size; both use `SiteHeader` with a `size` prop.

## 15. CI (`web` job)
`changes` gains output `web` from `scripts/ci/changed_paths.py` (patterns `web/`, `backend/api/openapi.yaml`, `eval/heldout/results.v2.json`, `design/fixtures/`; tests in `scripts/ci/tests/test_changed_paths.py`). The job: `ubuntu-24.04`, `permissions: contents: read`, `timeout-minutes: 25`, checkout with `persist-credentials: false`, actions pinned by SHA:
1. `actions/setup-node` (SHA looked up at T17.1) with the Node in `web/.node-version` and `cache: npm`.
2. `npm ci`.
3. `npm run lint`, `npm run format:check`, `npm run typecheck`.
4. `npm run gen:api` then `git diff --exit-code web/lib/api/schema.d.ts`.
5. `npm test`.
6. `npm run build` with `NEXT_PUBLIC_API_URL=https://api.example.invalid`, then `node scripts/check-build.mjs` (no Google Fonts host, no `msw`).
7. `npx lhci autorun` (`lighthouserc.json`: static dist `out`, URL `/`, 3 runs, `categories:performance` ≥ 0.9).
8. `npm run build:e2e` (flag `NEXT_PUBLIC_API_MOCKING=enabled`, copies the MSW worker into `out/`), cache of `~/.cache/ms-playwright` (existing `actions/cache` SHA), `npx playwright install --with-deps chromium`, `npm run e2e`.
`scripts/ci/tests/workflow_rules.py` (`CI_JOBS`) and `test_ci_workflow.py` list the jobs exactly, so both change with the job. The job holds no secret and no OIDC permission.

## 16. Test plan
| Layer | What |
|---|---|
| Backend (group B) | pytest: `via_of`, `ecosystem_of`, fetch `services`, progress in `get_scan`, `via` in graves and certificate, `evidence_links`, error enum, contract checker on real shapes, pre-B items. Terraform: offline `terraform test` for `modules/workflow`, `modules/api`, `envs/*` through `local-checks.sh` |
| Pure unit (web) | `normaliseRepo`; `parseQuery`, `scanHref`, `graveHref` (scoped npm round trip, bad IDs, missing parameters); `nextDelay`; `stageMap` (every stage in 6.2 plus an unknown one); error table vs the enum; `displayOf` (all state and overlay combinations, both overlays, unknown); `relationOf`; buckets (N = 1, 2, 7, ties, null priority); plots (multi-service package, clean plot, cap of 40, null `services`, title rules); cause text; sort and filter; `safeLink`; `formatEvidenceValue`; `parseDisplayPurl`; depth formula; contrast pairs from `globals.css`; fixture copies equal `design/fixtures` |
| Client | MSW: each route, pagination across 3 pages, 15 s timeout (fake timers), problem body, network error, malformed body |
| Components (Testing Library) | form (accepts, rejects, disabled while submitting, error focus); progress through every stage with fake timers, `progress` moving, hidden-tab pause, 5 failures then "Lost the trail"; results scene (stones, labels, roving keys, cap and link, clean plot, empty, partial banner, pre-B scan); chips and view toggle with URL and `localStorage`; table (sort, `aria-sort`, filter, window at 501 rows with `aria-rowcount`); certificate (full payload, payload with every optional field missing, direct and transitive descent, evidence links and hosts, 404, 400); 404 view |
| axe (Vitest) | one test per page and state: landing, progress, results scene, table, certificate, 404, error view |
| Playwright smoke (production export, MSW, Chromium) | landing → submit → each stage with moving progress → results → Lights On, sort, filter → certificate (including a direct load of `/scan?id=…` and of `/grave?scan=…&purl=…` with a scoped purl) → Back → unknown scan 404; per page: axe full rules with the WCAG 2.2 tags, a 360×800 check for horizontal scroll, a `reducedMotion: 'reduce'` check that `document.getAnimations()` is empty |
| Build checks | `check-build.mjs`: no `fonts.googleapis.com`, `fonts.gstatic.com`, `msw` or `mockServiceWorker` in the production `out/` |
| Lighthouse | `/` performance ≥ 90, median of 3 |
| Fixtures | `web/content/haunted-house/*` (real, 137 graves, 2 services, 2 cursed, 5 wounded alive) plus the overlay (N5), `empty`, `partial`, `large` (600 generated), `pre-b` (no `services`, `progress`, `via`), `failed-*` per code. The overlay and builders are typed against the generated types |

## 17. Risks
| Risk | Mitigation |
|------|------------|
| Lighthouse ≥ 90 with a large inline hero SVG and three font families | Preload two faces, CSS-only animation, no Framer on `/`, sized SVG, `content-visibility`; measured at the end of T9 and again in T16 |
| Host without clean URLs (`/scan` not mapped to `scan.html`) | Documented host contract; `serve` in tests; `infra-edge` Thu 26 |
| Scoped npm purls are double encoded (`%40` then `%2540` in the API path, and again in the query) | Unit tests with `@babel/core`; smoke test with a scoped purl; check against the dev API by hand (M2) |
| MSW service worker inside a static export | Test build only, worker copied into `out/` after the build, build check that production has none |
| Gateway 429 (throttle) looks like a network error without CORS headers | `network` copy covers it; polling retries |
| Step Functions intrinsic nesting (`MathAdd` inside `Format`) rejected at deploy | Offline tests check the strings only; first dev deploy is the real test; fallback is to write the count from the Lambda with an `UpdateItem` grant (N1 alternative) |
| `progressExamined` write contention on one item | Batches of 50 purls, about 5 writes a second at most; DynamoDB on demand handles it; `CountBatch` failures are swallowed |
| `typescript@7`, `eslint@10` or `vitest@5` peers not satisfied | T3 resolves and records the versions |
| jsdom has no layout, so contrast and overflow are not testable there | Contrast: token unit test and Playwright axe. Overflow and reduced motion: Playwright |
| Fixtures predate group B | Typed overlay (N5); optional recapture (M1) |

## 18. Deviations from this design, recorded at the end of T17
- The scenes are ported whole from the mockups (one component per scene), not as separate Moon, Fog and similar components. A fidelity test checks that every static path of the four mockups appears in the components. The art keeps the mockup hex values inside the SVG; tokens are used for the UI.
- `MockBoot` loads the mock service worker only when `NEXT_PUBLIC_API_MOCKING=enabled`. `next.config.ts` aliases `@/mocks/browser` to a stub in every other build, and `scripts/check-build.mjs` fails the build if mock code or a Google Fonts request reaches `out/`.
- The certificate title is "Certificate of Death" for dead and cursed packages and "Certificate of Condition" otherwise.
- Each signal on the certificate repeats its evidence link, with screen-reader-only context in the link text.
- `Chip` has `aria-label="Label, count"`.
- `useResource` derives "loading" from its key, and `useQueryString` uses `useSyncExternalStore`, because the lint rule `react-hooks/set-state-in-effect` is on.
- `app/icon.svg` provides the favicon, so the browser test can treat any unexpected 404 as a failure.

### Changes after the first live run (scan 01M8573XE1C7JZBBTKVZC23QHV-ba842f6efe73db6f)
- Cascade: `globals.css` had an unlayered `a { color: inherit }`, which beat every `text-*` utility on an anchor (blank "Exhume another" button, invisible toe-tag names). The rule is gone (preflight already does it, in a layer). `lib/css.test.ts` fails if an unlayered colour rule on an element selector comes back, and the browser test measures the contrast of both texts.
- Focus: a heading or region with `tabindex="-1"` that is not a control draws no ring; real controls, including the roving stones, keep it.
- Glow: an animation on an element replaces its `opacity`, so the cursed glow, the working lantern glow and the open-grave lantern glow animate a wrapping `<g>`. The art test fails if an element with an animation class has its own `opacity`.
- Results header: the hills are one layer, the moon and stars (`SkyObjects`) another, to the right of a 620 px text column (`left: max(680px, 52%)`), hidden under 768 px. Art is `z-0`, text `z-10`, the section is `isolate`.
- Evidence text: `plainText` writes `as_of` as the date of the evidence, a signal key as the signal's name, any other snake_case word with spaces. It runs over notes and warnings.
- Plots: stones in attention classes (`attentionClass`), cap 24, the rest counted by state (`restSentence`).
- Plot backdrop: the hill is `hairline`; the pickets keep the mockup silhouette with a `stone-line` edge on the moon side. The backdrop hangs from the top edge of the stones panel (its y = 200 is that edge), so the fence stands on the panel.

