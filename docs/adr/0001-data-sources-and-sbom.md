# ADR 0001 — Data sources, SBOM generation and model inputs

- **Status:** Accepted
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

## Consequences

- The S1/S1b split is validated on real data: express, uuid and moment would have been falsely marked Dead under the original rule.
- `six` computes to roughly 59, has no advisories and has very high downloads, so it classifies as Resting. The "finished, not dead" logic behaves as intended.
- Packages without a resolvable repo get lower confidence (fog) instead of a wrong verdict.