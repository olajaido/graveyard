"""The evaluation harness: measures the frozen v1 mortality model against labelled packages.

Purpose: score every labelled package from stored fixtures, compare the predicted
class with the label, apply the gate (PRD G2) and write `eval/results.json`.
The run is offline and deterministic: no network, no clock, no environment
variables, and two runs on the same files give byte-identical results.

Data folder: the data lives in the repo-root `eval/` folder (labelled set, staging
file, gate settings, frozen-weights hash, fixtures, results), not in this package.
The package finds it from `__file__`, never from the working directory.

Independence (D1): labels come from evidence about the package (a deprecation
notice, an archived repo, a maintainer statement) and never from Graveyard output.

Frozen weights (D6): the harness has no weights option. It records `model_version`
and the SHA-256 of `weights.v1.yaml`, and refuses to run if that hash changes.
A failing gate is reported, never tuned away; a change is a documented v2.

Direction of imports: this package may import application code (`core`, `cli`).
Nothing imports this package: no module in `core`, `sources`, `cli` or `mcp_server`.
"""
