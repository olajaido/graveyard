# Addition 3 (built 13 Nov 2026): finished-healthy top-up

Built under LABELLING.md Amendment 6, after Additions 1 and 2 were exhausted with the
effective `finished-healthy` count (rows passing the still-works check) below 20. Same method
as Addition 2: completeness phrases only, built before any of it is labelled, before any
Graveyard capture. No Graveyard output was used.

## Method
1. GitHub code search (`gh search code`, 13 Nov 2026); queries in `raw/queries.tsv`
   ("feature-complete", "considered complete", "considered feature complete",
   "is feature complete", "no new features planned", across README / README.md /
   README.markdown). Raw results: `raw/repos_q*.txt`; zero-result queries kept.
2. `map_repos_to_packages.py` (unchanged): package metadata must point at the exact repo.
3. `build_pool.py`: excludes anchors, plan, reserve, every Addition 1 and Addition 2 pool
   entry; sha256 order; owner cap 3 across Additions 1-3. Output `pool.tsv` (15: 8 npm, 7 pypi).

## Draw rule
Batches of 10 in rank order (the last batch takes what is left), drawn only while the
effective `finished-healthy` count is below 20 and only if merged rows + batch size <= 130.
Stop as soon as every section 3 minimum is met (effective count) or the pool is exhausted.
Names go to the coroner sorted by name, without source. Undrawn entries are never labelled.
If the minimum is still not met, the shortfall is reported as a limitation; no minimum is
lowered and no further addition is built.
