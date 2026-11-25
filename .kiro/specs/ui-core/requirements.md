# Spec: ui-core (LEAN)
> **Status:** REVISION 2 (23 Nov 2026): maintainer decisions applied (query-string routes, backend support group B, model v2 amendment, fixtures). For review. No task is started.
> **PRD:** the first part of `graveyard-ui` (PRD §8.3 GY-1 to GY-10, §8.10 LD-1 to LD-3, §9) and the page part of `death-certificate` (DC-1). Written to ship Mon 23 to Wed 25 Nov.
> **Goal:** a visitor opens the site, pastes a public GitHub repo, watches the exhumation, sees the graveyard (or the Lights On table), and opens a Death Certificate. Every screen reads the live `scan-backend` API. Every URL is shareable.
> **Delivery:** three pieces, in this order. (1) CORS, its own small PR (UI-CORS). (2) Backend support, group B, one PR (UI-B): the API gains the fields the UI needs, and `backend/api/openapi.yaml` is the contract. (3) The web app and the docs amendment.
> **Out of scope:** hosting and deploy, and pretty URLs (`infra-edge`, Thu 26); rites and PRs (Last Rites panel, "Perform the rites"); Coroner's Report, Séance, Vigil setup; SBOM upload and the instant demo entry point (LD-1 second and third); CSV export; ecosystem, scope and direct/transitive filters (GY-4 beyond state and service); moss, fog and wisps on stones (GY-2); cached-demo banner. **Deferred, shown as "Not recorded":** the cause-of-death narrative (`narrate`, Thu), "Born" and "Buried alongside" (`rite-reincarnate`, Fri). **Never recorded:** deprecation notice text and advisory titles (no third-party free text, `scan-backend` SB-DATA-2).
> **Lean rules (maintainer):** unit and component tests, one Playwright smoke; no mutation checks. The agent never runs `terraform plan/apply`, `terraform init` against a backend or the `aws` CLI, and never reads `~/.aws` or `AWS_*` variables (§0). Nothing is committed by the agent.
> **Sources:** `docs/PRD.md` §6, §7.4, §7.5, §8.3, §8.10, §9, §10.2; steering `product.md`, `security.md`, `tech.md`, `structure.md`, `frontend-design.md` (replaces `ui-theme.md`); `backend/api/openapi.yaml`; specs `scan-backend`, `mortality-model-v2`; mockups in `design/mockups/`; captured fixtures in `design/fixtures/haunted-house/`.

## Glossary for this spec
| Term | Meaning |
|------|---------|
| **Plot** | One fenced area of the scene for one service (a directory with a lockfile). |
| **Stone** | One grave drawn in a plot. A stone links to its certificate. |
| **Lantern path** | The six progress steps: Validate, Exhume, Identify, Trace roots, Autopsy, Pronounce. |
| **Not recorded** | The text shown where the API has no value. The UI never fills a gap with a made-up value. |
| **Via** | The first package that introduced a transitive package (the second to last node of its shortest path). Null for a direct dependency, or when no path was kept. |
| **Group B** | The backend support tasks B1 to B7 of this spec. |

## 1. Stack and build (UI-STK)
| ID | Requirement |
|----|-------------|
| UI-STK-1 | THE web app SHALL live in `web/` and SHALL be Next.js static export (`output: 'export'`, `trailingSlash: false`) with TypeScript, Tailwind CSS and Framer Motion, as PRD §10.2 and `structure.md` specify. Every dependency SHALL be pinned to an exact version, with a committed lockfile. |
| UI-STK-2 | THE package manager SHALL be **npm** with `web/package-lock.json`, so the dogfood hook and the Graveyard CLI can read the app's dependencies. |
| UI-STK-3 | BEFORE any dependency is added, it SHALL be checked with `autopsy_package` (skill `check-before-adding-dependency`). A Dead or Cursed result blocks the add, and the result for each runtime dependency SHALL be recorded in `design.md` section 10. |
| UI-STK-4 | FONTS (Cormorant Garamond, Inter, JetBrains Mono) SHALL be self-hosted from `@fontsource` packages (latin subset). The built site SHALL contain no reference to `fonts.googleapis.com` or `fonts.gstatic.com`, and a build check SHALL fail if one appears. |
| UI-STK-5 | THE API base URL SHALL come from `NEXT_PUBLIC_API_URL` at build time (an empty value means same origin). The production build SHALL fail when it is unset. No secret, token, account ID or API ID SHALL be written in any committed file (`security.md` T6). |
| UI-STK-6 | `npm run dev` SHALL serve on port 5173, so the dev API's CORS origin (UI-CORS-1) matches. |
| UI-STK-7 | THE project SHALL have ESLint (flat config, `eslint-config-next` with its jsx-a11y rules) and Prettier, with scripts `lint`, `format:check`, `typecheck`, `test`, `build`, `gen:api`. TypeScript SHALL run in strict mode. |
| UI-STK-8 | THE production build SHALL contain no mock code: no `msw`, no `mockServiceWorker.js`. A build check SHALL fail otherwise. |

## 2. Routes and shareable URLs (UI-RT)
| ID | Requirement |
|----|-------------|
| UI-RT-1 | THE app SHALL serve three static pages: `/` (landing and form), `/scan?id=<scanId>` (progress, then results when `COMPLETE`) and `/grave?scan=<scanId>&purl=<encoded purl>` (certificate). The purl SHALL be encoded with `encodeURIComponent`, so `pkg:npm/%40babel/core@7.0.0` is written `pkg%3Anpm%2F%2540babel%2Fcore%407.0.0`. The page's own view state (`view`, `state`, `service`, `sort`, `dir`) SHALL live in the same query string. A reload or a pasted link SHALL show the same screen. There SHALL be no dynamic path segment and no placeholder page. |
| UI-RT-2 | THE client SHALL read the query on the client after mount, SHALL treat a missing `id` or `scan`, or a scan ID that does not match `^[0-9A-HJKMNP-TV-Z]{26}-[0-9a-f]{16}$`, or a `purl` that does not start with `pkg:`, as an unknown link without calling the API, and SHALL decode each value exactly once. |
| UI-RT-3 | A link the UI cannot resolve (UI-RT-2), a scan the API does not know (404), or a purl that is not in the scan (404), SHALL show a friendly 404 in the theme with a link home (and, for a certificate, a link back to the scan). The page SHALL say that scans are kept for 30 days (`security.md`). |
| UI-RT-4 | THE web app SHALL document its host contract for `infra-edge` in `web/README.md`: static files only; an extensionless path (`/scan`, `/grave`) maps to its `.html` file (clean URLs); `404.html` for the rest; the API origin in `connect-src`. Pretty URLs are a later `infra-edge` concern. Tests SHALL serve the export with `serve`, whose defaults match that contract. |
| UI-RT-5 | EACH page SHALL set a unique `document.title` ("Graveyard · owner/name", "lodash.template@3.6.2 · Graveyard"), and after an in-app navigation SHALL move focus to the page `<h1>` (`tabindex="-1"`). |

## 3. API client and data (UI-API)
| ID | Requirement |
|----|-------------|
| UI-API-1 | TypeScript types SHALL be generated from `backend/api/openapi.yaml` (`npm run gen:api`), as updated by group B, and committed. CI SHALL fail if regenerating changes the committed file. |
| UI-API-2 | THE client SHALL call only the four documented routes, build each URL from the base URL and encoded path parts, send no credentials and no custom header, and time out after 15 s. It SHALL never fetch a URL taken from API data. |
| UI-API-3 | EVERY failure SHALL become one `ApiError` of kind `problem` (RFC 9457 body, with status), `network` (fetch failed, including a CORS or throttle response the browser hides), `timeout` or `parse` (body not as expected). The UI SHALL never show a raw exception message. |
| UI-API-4 | THE graves list SHALL be read with `limit=200` and the `nextCursor` the API returns, until `nextCursor` is null. The cursor SHALL be passed back unchanged and never built by the client. |
| UI-API-5 | AFTER group B the generated types SHALL cover every certificate and scan field, so the client SHALL use no hand-written guard for them. The only narrowing that remains is for values typed as any JSON value (an evidence `value`). A value that does not fit SHALL render as "not recorded", never throw. |
| UI-API-6 | RESPONSES SHALL be cached in memory per session by URL, so moving between the scene, the table and a certificate does not refetch a completed scan. A scan that is not `COMPLETE` SHALL never be cached. |
| UI-API-7 | A scan created before group B was deployed has `services`, `progress` and `via` as null. The UI SHALL render it, falling back to plots derived from the graves and omitting the manifest name and the "via" text. |

## 4. Landing (UI-LAND)
| ID | Requirement |
|----|-------------|
| UI-LAND-1 | THE landing page SHALL contain, in order and as in `Main.dc.html`: the hero over the night scene with the repo form, the example result strip, "The autopsy, in four acts", "Six states of being", the evidence stone, and the fenced footer. The nav SHALL link to those sections and to the GitHub repo. |
| UI-LAND-2 | THE form SHALL have a visible `<label>` ("Public GitHub repository"), the `github.com/` prefix, and a `<button type="submit">` "Exhume". It SHALL accept `owner/name`, `github.com/owner/name` and `https://github.com/owner/name(.git)(/)`, normalise them to `owner/name`, and reject anything else inline (before any request) with the `INVALID_INPUT` message. The client check SHALL mirror the server's `parse_repo` rules, and the server remains the authority. |
| UI-LAND-3 | ON submit THE UI SHALL `POST /v1/scans {"source":{"type":"github","repo":"owner/name"}}`, disable the button and show "Digging…" while waiting, and on 202 navigate to `/scan?id=<scanId>`. On failure it SHALL stay on the page, show the themed error (UI-ERR-2) tied to the input with `aria-describedby`, and move focus to the input. |
| UI-LAND-4 | THE "Six states of being" cards SHALL use the PRD definitions as amended for model v2: **Dead** is declared dead (deprecated on its registry, archived, or retired by its maintainer); **Ailing** is declining maintenance signals; **Cursed** is a known vulnerability with no fix, on any state; **Wounded** is a fixable vulnerability or an upgrade advised, on any state. The page SHALL NOT say Cursed means dead or Wounded means alive, and SHALL NOT say a score makes a package Dead. Each card SHALL show the plain term beside the themed one. |
| UI-LAND-5 | THE example strip SHALL read its numbers from the committed fixture `scan.json` of `haunted-house` (`counts`, `source.repo`, `updatedAt`) and show its date, so no figure is typed into a component. THE evidence stone SHALL read the held-out result (numerator, denominator, interval, verdict) from `eval/heldout/results.v2.json` at build time, and the build SHALL fail if the file or fields are missing. WHEN the verdict is not PASS the stone SHALL say the result is inconclusive, as the mockup does. |
| UI-LAND-6 | THE landing page SHALL NOT offer SBOM upload or an instant demo (out of scope). The input SHALL be pre-filled with `olajaido/haunted-house`, as in the mockup. |

## 5. Exhumation progress (UI-PRG)
| ID | Requirement |
|----|-------------|
| UI-PRG-1 | WHILE a scan is `QUEUED` or `RUNNING` THE page SHALL poll `GET /v1/scans/{id}` starting at 1.5 s and multiplying the delay by 1.5 up to 5 s, and SHALL stop on `COMPLETE` or `FAILED`. It SHALL pause while the tab is hidden and poll at once when it returns. |
| UI-PRG-2 | THE lantern path SHALL derive its state from the `stage` string only: `VALIDATE`, `FETCH`, `SBOM`, `GRAPH`, `AUTOPSY`, `CLASSIFY`, `DONE`, with the mapping in `design.md` section 6.2. A stage the mapping does not know SHALL leave the lanterns as they were and show "Working…". |
| UI-PRG-3 | WHILE the stage is `AUTOPSY` and `progress` is not null, THE page SHALL show "N of M examined" from `progress.examined` (clamped to `progress.total`) and `progress.total`, and SHALL draw the dig depth in the open-grave scene from the same numbers (design 5.3). It SHALL show per-state counts only when `counts` is returned (after `COMPLETE`), and SHALL NOT show a running tally by state, a per-package list or a percentage figure. Elapsed time since `createdAt` MAY be shown. |
| UI-PRG-4 | A polite `role="status"` region SHALL announce each stage change and the outcome, not each poll, and the examined count not more often than every 10 %. The lantern list SHALL mark the current step with `aria-current="step"`. |
| UI-PRG-5 | ON `COMPLETE` THE page SHALL swap to the results view at the same URL, focus the results `<h1>` and announce "Exhumation complete". A link opened on an already `COMPLETE` scan SHALL go straight to results. |
| UI-PRG-6 | ON `FAILED` THE page SHALL show the themed error for `error.code` (UI-ERR-1) with the scan's repo and a link to start again. |
| UI-PRG-7 | ON a failed poll (network, 429, 5xx) THE page SHALL retry with backoff and, after 5 failures in a row, show "Lost the trail" with a Retry button. A 404 SHALL show the 404 page (UI-RT-3). |
| UI-PRG-8 | THE header SHALL have a "Copy link to this scan" button that copies the page URL and confirms in the status region. |

## 6. Errors (UI-ERR)
| ID | Requirement |
|----|-------------|
| UI-ERR-1 | THERE SHALL be one themed message (title, one plain sentence, next action) for each value of the `error.code` enum in `openapi.yaml` (UI-B-4). The table SHALL be typed so `tsc` fails when the enum gains a code it lacks, and a test SHALL fail when the table and the enum differ in either direction. An unknown code at runtime SHALL fall back to the API's `error.title` under a generic themed heading. |
| UI-ERR-2 | THE messages SHALL also cover the HTTP outcomes: POST 400, 413, 429, 503 and other 5xx; GET 400 and 404; and network, timeout and parse failures. A message SHALL NOT suggest SBOM upload or any feature that does not exist in the UI. |
| UI-ERR-3 | EVERY error view SHALL tell the user what to do (retry, edit the repo, go home), SHALL mark whether a retry can help, and SHALL be announced (focus on its heading or `role="alert"`). |

## 7. Graveyard scene (UI-GY)
| ID | Requirement |
|----|-------------|
| UI-GY-1 | THE results header SHALL show the repo, the completion date, one summary sentence built from `counts` (total, dead, cursed, ailing; cursed is not described as a subset of dead), "The living: N · Resting: M", and the fog banner when `partial` is true, naming `counts.unscored` when it is above zero. |
| UI-GY-2 | THE scene SHALL draw one fenced plot per entry of `scan.services`, including a service with no graves, which shows "Nothing buried here. This plot is clean." Plots SHALL be ordered by their highest priority, then by `id`. A plot title SHALL be derived from the service `id` ("." gives "The root plot", "services/worker" gives "The worker plot") and its subtitle SHALL show the `id`, the ecosystems and the lockfile names (the last segment of each `manifests[].path`). Where `services` is null (UI-API-7) plots SHALL come from the graves, without manifest names. |
| UI-GY-3 | A stone SHALL be drawn for every grave the API lists (Resting, Ailing, Dead, or Cursed or Wounded on any state), with the grave type chosen by the rule in `frontend-design.md` section 5, in the order of priority. A package in several services SHALL appear in each of its plots. |
| UI-GY-4 | STONE size SHALL be one of four buckets by the rank of `priority` among all graves of the scan (design 4.4). A grave with null priority SHALL use the smallest. The legend SHALL say size is relative to this scan. |
| UI-GY-5 | EACH plot SHALL draw at most 24 stones, ordered by attention class (cursed, dead, wounded, direct ailing, direct resting, transitive ailing, transitive resting) and then by priority, and, when more exist, one line below the stones that counts the rest by state ("Also in this plot: 52 ailing and 9 resting, mostly brought in by other packages") followed by a link "see them in Lights on" that opens the table filtered to that service. |
| UI-GY-6 | A stone SHALL be a link to its certificate with the accessible name "name version, State and overlays, priority N of M" (rank in the full sorted list). Under it SHALL be visible text: the name, and the version with `dev` and "via `<name>`" markers (from `via`). |
| UI-GY-7 | STONES in a plot SHALL use roving tabindex: one tab stop per plot, arrow keys move between stones, Home and End jump, Enter opens. |
| UI-GY-8 | THE state chips (All, Dead, Cursed, Ailing, Resting, Wounded) SHALL be toggle buttons with `aria-pressed` and a count from `counts` (All shows the number of graves). Selecting one filters the scene and the table. A plot with no match SHALL say so. |
| UI-GY-9 | WHEN the API lists no graves THE page SHALL show the empty state "No graves here. Your dependencies live." with the counts (GY-9). The share card is out of scope. |
| UI-GY-10 | THE view toggle ("Graveyard" and "Lights on") SHALL be buttons with `aria-pressed`, always visible, SHALL be reflected in the URL (`view=table`) and SHALL be remembered per browser (`localStorage`, GY-5), with the URL taking priority. |
| UI-GY-11 | THE results header SHALL list up to five "Dig these first" toe tags: the five highest-priority graves, each a link to its certificate showing name and version, state text, and "direct" or "via `<name>`" (transitive without `via` shows "transitive"). |

## 8. Lights On table (UI-TBL)
| ID | Requirement |
|----|-------------|
| UI-TBL-1 | THE table SHALL be a real `<table>` on parchment with a caption and columns Package (link to the certificate), State, Priority, Cause, Relationship, Scope, Service, and the same filter chips as the scene. |
| UI-TBL-2 | IT SHALL sort by Package (name, then version), State (Cursed, Dead, Ailing, Resting, other) and Priority (default, highest first). Each sortable header SHALL be a `<button>` inside its `<th>`, with `aria-sort` on the `<th>`. |
| UI-TBL-3 | "State" SHALL show a text pill ("dead · cursed"). "Cause" SHALL be built from `state`, `deadReason`, `cursed`, `wounded` only (design 4.5). "Relationship" SHALL be "direct", "via `<name>`" or "transitive". |
| UI-TBL-4 | A wide table SHALL scroll inside a focusable, labelled region and SHALL NOT scroll the page at 360 px. |
| UI-TBL-5 | WHEN more than 500 rows match, THE table SHALL render a window of rows (fixed row height, spacer rows, `aria-rowcount` and `aria-rowindex`). At 500 rows or fewer it SHALL render all rows. |

## 9. Death Certificate (UI-CERT)
| ID | Requirement |
|----|-------------|
| UI-CERT-1 | THE certificate SHALL render, from `GET /v1/scans/{id}/graves/{purl}`: name and version (parsed from the purl), Pronounced (state and `deadReason`), Complications (cursed, wounded), Cause of death, Ecosystem, Place of rest (services and scope), Mortality, Confidence, Priority, the evidence, the dependency path, the issue date (`asOf`) and the footer (scan ID, `modelVersion`). |
| UI-CERT-2 | "Cause of death" SHALL be a fixed template over `state`, `deadReason`, the overlays and the largest non-null `contributions`. It SHALL NOT be generated text and SHALL NOT state a fact the payload does not hold. WHEN a `narrative` field exists in a later API version, a later spec shows it. |
| UI-CERT-3 | "Line of descent" SHALL draw each entry of `examplePaths` as the service, then each node of `nodes`, ending at this package, with a state badge on each node that is in the graves list already fetched for the scan (nodes not in it get no badge, and no extra request is made for them). It SHALL say "You chose this package yourself" when the package is direct, and otherwise name the package in `via`. It SHALL show "N paths, showing M" from `pathCount`. |
| UI-CERT-4 | "Evidence on file" SHALL list, for each signal that has a value, its plain name, its evidence kind, the value, the fetch time and the `note`, and the link-outs from `evidenceLinks` that cover that signal (for example "Read the notice on npmjs.com", "See the repository on github.com", "Read the advisory on osv.dev"). A signal without a value SHALL be listed as "not recorded" with the `note`. It SHALL show no notice text and no advisory title. Advisories (`signals.s7_advisories`) SHALL show ID, "fix available" or "no fix", and published date, each linked to its advisory link. A link SHALL be rendered only when it is `https` on `www.npmjs.com`, `pypi.org`, `github.com`, `osv.dev` or `deps.dev`. |
| UI-CERT-5 | A field the API returns as empty SHALL render "Not recorded" with no invented value. A field the API does not return at all ("Born", the "Buried alongside" panel, the narrative, the deprecation notice text, advisory titles) SHALL NOT be drawn: no placeholder and no wording about a later release. The evidence text SHALL contain no internal identifier (`as_of`, `s5_committers`): the date is written out and signal keys are written as their names. |
| UI-CERT-6 | `warnings` SHALL be shown in a short "Notes on the evidence" block (source, signals affected, detail). |
| UI-CERT-7 | THE page SHALL have "Back to owner/name" (to the scan, in the remembered view) and "Copy certificate link". The wax seal SHALL be decorative, with the state word and `asOf` date. There SHALL be no rites button. |

## 10. Quality (UI-Q)
| ID | Requirement |
|----|-------------|
| UI-Q-1 | **WCAG 2.2 AA.** Every page and state under test SHALL have zero axe violations for the tags `wcag2a`, `wcag2aa`, `wcag21aa`, `wcag22aa`. All functions SHALL work by keyboard alone. Focus SHALL be visible with the ring in `frontend-design.md` section 7. Controls SHALL be real buttons, links and labelled inputs. Progress SHALL be announced through `aria-live` (UI-PRG-4). |
| UI-Q-2 | **Contrast.** A unit test SHALL assert every text and UI pair in the steering table from `globals.css`. |
| UI-Q-3 | **Reduced motion.** UNDER `prefers-reduced-motion: reduce`, no CSS animation, transition or Framer Motion animation SHALL run on any page. A browser test SHALL assert `document.getAnimations()` is empty on the landing, progress and results views. |
| UI-Q-4 | **Responsive.** EVERY page SHALL work from 360 px wide with no horizontal page scroll. A browser test at 360×800 SHALL assert it on each page. |
| UI-Q-5 | **Decorative SVG** SHALL be `aria-hidden`. A component test SHALL assert that every `<svg>` in each page is `aria-hidden` unless it has an accessible name. |
| UI-Q-6 | **Performance.** Lighthouse performance on `/` in the production build SHALL be at least 90 (mobile emulation, median of 3 runs). The landing route SHALL NOT include Framer Motion. |
| UI-Q-7 | **No invented data.** A test SHALL render each page from fixtures that omit the optional fields and assert "not recorded" appears and no placeholder text from the mockups (`[notice text`, `142 of`, `68%`) is in the DOM. |

## 11. Tests and CI (UI-TEST, UI-CI)
| ID | Requirement |
|----|-------------|
| UI-TEST-1 | VITEST with Testing Library SHALL cover: the pure modules (repo normalisation, query parsing, stage map, error table, grave model, buckets, plots, sorting, filtering, cause text, polling schedule, purl parsing, link guard) and each page and its main states (loading, empty, error, 404, partial, pre-group-B scan). |
| UI-TEST-2 | THE API SHALL be mocked with MSW, from one handler module with a scripted scan (QUEUED, RUNNING at each stage including `AUTOPSY` with a moving `progress`, COMPLETE or FAILED). Fixtures SHALL be built from the committed captures in `web/content/haunted-house/` (verbatim copies of `design/fixtures/haunted-house/`, checked byte for byte by a test) plus a typed overlay for the fields group B adds, and SHALL type-check against the generated types. After group B is deployed to dev, the fixtures SHALL be recaptured from a fresh dev scan and the overlay removed (task M1). |
| UI-TEST-3 | EACH page SHALL have an axe test in Vitest (axe-core, color-contrast excluded because jsdom has no layout) and the Playwright smoke SHALL run axe with the full rule set on each page. |
| UI-TEST-4 | ONE Playwright smoke SHALL run the full flow on the production export against MSW (browser service worker, in the test build only): landing, submit, progress through every stage, results scene, Lights On (sort and filter), a certificate, Back, and a 404. |
| UI-CI-1 | `.github/workflows/ci.yml` SHALL gain a `web` job: install with cache (`npm ci`, npm cache), lint and format check, typecheck, `gen:api` freshness, unit tests, production build, the build checks (UI-STK-4, UI-STK-8), Lighthouse (UI-Q-6), the test build and the Playwright smoke. It SHALL follow the workflow rules (SHA-pinned actions, `permissions` read only, timeout, no secrets). |
| UI-CI-2 | THE `changes` job SHALL output `web`, true when a file under `web/`, `backend/api/openapi.yaml`, `eval/heldout/results.v2.json` or `design/fixtures/` changes, and the `web` job SHALL run only then (or on a first push). |

## 12. CORS, its own PR (UI-CORS)
| ID | Requirement |
|----|-------------|
| UI-CORS-1 | THE `api` module SHALL allow the methods `GET`, `POST` and `OPTIONS` and the header `content-type` for the origins in `cors_allowed_origins` (the variable already exists, empty by default, `*` rejected, SB-API-9). `envs/dev` SHALL default the variable to `["http://localhost:5173"]`. `envs/prod` SHALL stay empty (the real domain comes with `infra-edge`). |
| UI-CORS-2 | OFFLINE `terraform test` SHALL assert, in the module: the exact method set, the exact header set, no `*`; and in the roots: dev lists `http://localhost:5173` only, prod lists none. |
| UI-CORS-3 | THE change SHALL touch only `infra/modules/api`, `infra/envs/dev` and `infra/envs/prod` (tests and variable text), and the env-roots guard `scripts/ci/tests/test_env_roots.py`; not `infra/bootstrap` or `github-oidc`. The apply roles already allow `apigateway:PATCH` on `/apis/*` (statement `ManageHttpApis`), which is the call `UpdateApi` makes. The agent SHALL NOT apply it; CI deploys on merge to `main`. It SHALL be a PR of its own, merged before any UI task starts. |

## 13. Backend support, group B, one PR (UI-B)
`backend/api/openapi.yaml` is the contract: each item updates it and its tests in the same change. No IAM change is needed (design 11).
| ID | Requirement |
|----|-------------|
| UI-B-1 | **Stages.** THE scan's `stage` SHALL take the distinct values `QUEUED`, `VALIDATE`, `FETCH`, `SBOM`, `GRAPH`, `AUTOPSY`, `CLASSIFY`, `DONE`. THE state machine SHALL write `SBOM` before `GenerateSBOM` and `AUTOPSY` before `AutopsyMap`, and `openapi.yaml` SHALL list the values as an enum. |
| UI-B-2 | **Progress.** `GET /v1/scans/{id}` SHALL return `progress: {examined, total}` while the stage is `AUTOPSY`, and `null` otherwise. `total` is the number of unique purls (`BuildGraph` output). `examined` comes from an atomic DynamoDB counter on the scan item that each autopsy batch increments by the number of purls it handled (`ok + cached + failed`). The counter write is best effort: a failure of it SHALL be caught and ignored and SHALL never fail a batch or the scan. THE API SHALL never return `examined` above `total`, and the UI SHALL also clamp it. There SHALL be no per-state tally during the scan. |
| UI-B-3 | **Via and services.** EACH item of `GET /v1/scans/{id}/graves`, and the certificate, SHALL include `via`: the purl of the first introducer (the second to last node of the first example path), null for a direct dependency or when no path was kept. `GET /v1/scans/{id}` SHALL include `services: [{id, manifests: [{ecosystem, path}]}]`, one entry per service and no duplicate `id`, where `id` equals the directory value used in `GraveSummary.services`, `ecosystem` is `npm` or `pypi`, and `path` is the lockfile path in the repository, in name order. A service with no graves SHALL still be listed. |
| UI-B-4 | **Error codes.** `Scan.error.code` SHALL be an enum in `openapi.yaml` of the twelve codes of `core/scan/errors.py`. A backend test SHALL fail when the enum and `CODES` differ. |
| UI-B-5 | **Schemas.** `openapi.yaml` SHALL give exact schemas, with `required` lists, for `Scan` (`source`, `stage`, `services`, `progress`), `GraveSummary`, and the certificate: `exposure`, `exposureAssumed`, `servicesAffected`, `repo`, `examplePaths`, `signals`, `evidence` (the eleven signal keys, each `{value, source_url, fetched_at, extra_source_urls, note}`), `contributions`, `normalisedRisks`, `warnings`, `evidenceLinks`. A backend test SHALL check real responses against the schemas (keys, `required`, enums, types). The web types SHALL be regenerated and the hand-written guards dropped where the types now cover the field. |
| UI-B-6 | **Evidence links.** THE certificate SHALL include `evidenceLinks: [{kind, url, signals}]`, built by the server at read time only from the components of the parsed purl, the stored repo and the advisory IDs, each URL-encoded, on the fixed hosts `www.npmjs.com`, `pypi.org`, `github.com`, `osv.dev`, `deps.dev` and no other. `kind` is `registry`, `repository`, `advisory` or `deps_dev`, and `signals` lists the evidence keys the link supports. A test SHALL show that no crafted purl, repo or advisory ID can produce a link to another host. It SHALL carry no third-party free text, and the raw `source_url` API endpoints stay as they are. |
| UI-B-7 | **Compatibility and spec.** Every new field SHALL be present as `null` (never missing) for scans stored before the change. The change SHALL be one PR with tests, the `scan-backend` spec SHALL get an amendment A3 listing the changed requirements (SB-API-3, SB-API-4, SB-API-5, SB-WF-1, SB-ERR-1), and `scripts/ci/guards.py` and the backend suite SHALL pass. |

## 14. Docs amendment (UI-DOC)
| ID | Requirement |
|----|-------------|
| UI-DOC-1 | `docs/PRD.md` SHALL get an amendment (Appendix D, v1.4, 23 Nov 2026) stating that model v2 supersedes the "or score ≥ 60" rule of §7.4: Dead means `s1_declared_death` only (`dead_reason = "declared"`), and a package that v1 classed Dead by score is Ailing. §6 (Glossary) and §7.4 (Dead and Ailing rows) SHALL be edited to match, the §11 steering table SHALL name `frontend-design.md` instead of `ui-theme.md`, and `.kiro/steering/product.md` SHALL get the same glossary change. |
| UI-DOC-2 | `.kiro/steering/ui-theme.md` SHALL be a one-line pointer to `frontend-design.md`, and what still applies SHALL be carried into `frontend-design.md`. **Done with this revision.** |

## 15. Design system steering (UI-STEER)
| ID | Requirement |
|----|-------------|
| UI-STEER-1 | `.kiro/steering/frontend-design.md` SHALL hold the colour tokens (surfaces, text, parchment, six states with bright, ink and pill values), type, spacing, radii, motion rules, the state to grave mapping and the rules carried over from `ui-theme.md`. **Done with this spec.** |
