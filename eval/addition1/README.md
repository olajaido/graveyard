# Addition 1 (13 Nov 2026): candidate pools

Built after batches 1-5 and the reserve left a shortfall against the section 3 minimums
(51 merged rows: 33 dead, 16 alive, 2 ailing, 0 finished-healthy; 7 dead on
maintainer_statement/eol_announcement). Built before any Graveyard capture. No Graveyard
output was used.

## Method (mechanical; no hand-picking)

1. GitHub code search (`gh search code`, 13 Nov 2026) for:
   - repostatus.org badges in README.md / README.rst: inactive, unsupported, abandoned, moved;
   - README phrases: "feature complete", "feature-complete", "considered stable",
     "considered done", "stable and complete", "no further development",
     "looking for maintainers", "maintainers wanted", "maintenance mode",
     "no longer maintained".
   Raw repository lists: `raw/repos_*.txt` (code search results are not stable over time,
   so these files are the frozen source).
2. `map_repos_to_packages.py`: a repo becomes a candidate only if a PyPI or npm package of
   that name (or a normalised variant) has metadata (homepage, project URLs, repository)
   pointing at that exact repo. Scoped npm packages are skipped. Output: `raw/mapped_*.tsv`.
3. `build_pools.py`: removes the nine anchors, the 101 plan candidates and the 15 reserve
   candidates; assigns each package to one pool by its source query
   (F: completeness/stability sources; A: maintenance/maintainer-search sources;
   D: abandoned/moved/no-longer-maintained sources; priority F > A > D); orders each pool by
   sha256("<ecosystem>:<name>"); caps any one GitHub owner at 3 packages across all pools.
   Output: `pools.tsv` (F 112, A 79, D 15; 110 pypi, 96 npm).

Pool membership says which search found a package. It is not a label and not a prediction.
The coroner never sees pools.tsv or the pool of any name (fs_read is denied on this folder).

## Draw rule (fixed before labelling any addition candidate)

Batches of up to 20, names taken strictly in rank order within each pool, counts taken from
merged rows after each merge:
- 12 from F while `finished-healthy` < 20;
- 6 from A while `ailing` < 10;
- 2 from D while `dead` rows on maintainer_statement/eol_announcement < 10;
- if all three are met but rows < 90 or pypi < 30, up to 20 from F (pypi only, if pypi < 30).
Stop as soon as every section 3 minimum is met, or the pools are exhausted. Entries not
drawn are never labelled. Names within a batch are presented to the coroner sorted by name,
without pool or source.

Reproduce: `python3 build_pools.py` regenerates pools.tsv from raw/ (mapping step needs
network access to pypi.org and registry.npmjs.org).
