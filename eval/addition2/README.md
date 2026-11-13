# Addition 2 (built 13 Nov 2026): finished-healthy top-up

Built under LABELLING.md Amendment 1 point 4: pool F of Addition 1 is exhausted with
`finished-healthy` below 20. Built from completeness and stability phrases only, by the
Addition 1 method, before any of it is labelled. No Graveyard output was used.

## Method
1. GitHub code search (`gh search code`, 13 Nov 2026), queries in `raw/queries.tsv`
   (phrases: "feature-complete", "feature complete", "considered complete",
   "complete and stable", "stable and complete", across README.md / README.rst / README /
   README.txt, some with a disambiguating term). Raw results: `raw/repos_q*.txt`. Queries
   that returned 0 are kept in queries.tsv for the record.
2. `map_repos_to_packages.py` (same as Addition 1): a repo becomes a candidate only if a PyPI
   or npm package's metadata points at that exact repo. Output `raw/mapped.tsv`.
3. `build_pool.py`: excludes anchors, plan, reserve and every Addition 1 pool entry; orders by
   sha256("<ecosystem>:<name>"); caps any GitHub owner at 3 across Additions 1 and 2.
   Output `pool.tsv` (25: 13 npm, 12 pypi).

## Draw rule
Batches of up to 20 in rank order while `finished-healthy` < 20 and rows < 130; stop as soon
as every section 3 minimum is met or the pool is exhausted. Names are given to the coroner
sorted by name, without source. Entries not drawn are never labelled. If the minimum is still
not met, the shortfall is reported as a limitation (Amendment 1 point 4).
