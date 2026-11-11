# ADR 0001 — Data sources, SBOM generation and model inputs

- **Status:** Accepted; amended 11 Nov 2026 (decisions 11 to 13)
- **Date:** 3 Nov 2026
- **Evidence:** `docs/SPIKES.md`, `spikes/`

## Context

The PRD assumed that signals S1–S9 were available from deps.dev, OSV, npm and PyPI. It also left open whether Syft or our own parsers should turn lockfiles into SBOMs. Spikes ran against 11 real packages (npm: request, node-uuid, moment, express, left-pad, uuid; PyPI: pycrypto, nose, requests, pycryptodome, six) and Syft v1.56.0.

## Decisions

1. **SBOM:** Syft v1.56.0 (pinned) turns lockfiles into CycloneDX JSON. Its output includes the `dependencies` graph, so we can tell direct from transitive. Find the root via the fixture component's `bom-ref` in `components`, not `metadata.component`. Accept CycloneDX 1.5–1.7 uploads.
2. **Scope enrichment (EX-8):** Syft gives no runtime/dev scope. Read it from the lockfile:
   - `package-lock.json` `packages[*].dev` / `devOptional`;
   - `poetry.lock` groups;
   - `uv.lock` dev groups;
   - `requirements.txt` counts as runtime.
3. **PyPI death:** PyPI has no project-status or deprecation field, and dead packages still claim "Production/Stable". PyPI S1 comes only from GitHub `isArchived`; otherwise death is detected through staleness.
4. **GitHub Reader app is P0.** S3 (`pushedAt`), S5 (recent commit authors), S6 (issue counts) and `isArchived` are only available from GitHub. Use one batched GraphQL query per group of repos.
5. **S6 v1 uses all-time** open/(open+closed). A 12-month window would need the search API (30 requests per minute), so it is deferred to model v2.
6. **Popularity = weekly downloads** (npm downloads API, pypistats), because deps.dev v3 has no dependents count. The Resting rule uses `resting_min_weekly_downloads: 10000`.
7. **Repo resolution (EX-9):** deps.dev `SOURCE_REPO` → registry `repository` → PyPI `project_urls`, normalised to `github.com/<owner>/<repo>`. Formats seen include `git+https://…` and `github:owner/repo`. The normaliser is a property-based-testing target.
8. **Vulnerabilities:** OSV is the primary source (fix ranges, published dates). deps.dev `advisoryKeys` is used for cross-checking only.
9. **Scorecard:** treat −1 as missing. `overallScore` was never −1 in the sample; individual checks often were.
10. **Bedrock:** EU cross-region inference profiles are available in eu-west-2. Narrate uses `eu.anthropic.claude-haiku-5-5` and rites use `eu.anthropic.claude-sonnet-5-5`, both IDs in SSM. Never use `global.` profiles. IAM must allow the profile ARN plus the underlying EU foundation-model ARNs.
11. **Syft and dev dependencies (11 Nov 2026, `docs/SPIKES.md` Q7):** Syft 1.56.0 drops the `dev: true` packages of a `package-lock.json` unless `SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES=true`, and never links a project's root to its dev direct dependencies (npm `devDependencies`, uv dev groups). Every place that runs Syft for the pipeline sets the variable. This amends decision 1: the root's `dependsOn` lists only the runtime directs.
12. **Direct edges from the lockfile:** before the graph is built, add `root -> direct` for every direct dependency the lockfile declares and the root does not reach (decision 2 already reads scopes from the lockfile). Only root-sourced edges are added; nothing is removed or changed. The root is the unreferenced entry whose package is not a declared direct dependency, or `metadata.component` when there is none. Without this, an orphan dev package with edges of its own is read as a second root and dropped. Implemented in `backend/cli/augment.py`; the Lambda path must reuse it.
13. **Gate only on evidence that was seen:** a package whose verdict rests on the score (Dead *by score*, or Ailing) while a scored signal is missing because its source was skipped or failed (no GitHub token, rate limit, network, malformed response) is *unverified* and is not gated by `--fail-on`. A signal that is missing because the data does not exist (no repository resolved, a 404) does not count. Declared Dead is always gated. Cursed is gated when a no-fix advisory meets the model's age rule on its own; a Cursed that holds only through the Dead/Ailing bypass follows its base state. The sources already say which: `SourceWarning.signals` lists the signals that ended up missing because of a failure.

## Consequences

- The S1/S1b split is validated on real data: express, uuid and moment would have been falsely marked Dead under the original rule.
- `six` computes to roughly 59, has no advisories and has very high downloads, so it classifies as Resting. The "finished, not dead" logic behaves as intended.
- Packages without a resolvable repo get lower confidence (fog) instead of a wrong verdict.- The CLI's first real-Syft run showed that the stub SBOMs had assumed edges Syft does not write (decisions 11 and 12). Fixtures are now real Syft output.
- A token-less run can compute a Dead-by-score verdict from only the signals that did not need GitHub (`six`: 68.6 from S2, S4 and S8, against Resting with all signals). Decision 13 keeps such a verdict visible but out of the gate.

