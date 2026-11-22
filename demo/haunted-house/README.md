# haunted-house

A deliberately haunted demo repository for [Graveyard](https://github.com/olajaido/graveyard).

It holds dependency manifests and nothing else: there is **no app code** and nothing here is meant to be installed or
run. The manifests pin a mix of packages that are dead (deprecated or archived), ailing or quiet, and alive, so a
Graveyard scan has something to find.

| Path | What it is |
|------|------------|
| `package.json`, `package-lock.json` | A Node "service" with 10 direct dependencies (9 runtime, 1 dev). The lockfile was generated with `npm install --package-lock-only --ignore-scripts`; no package in it has an install script. |
| `services/worker/requirements.txt` | A Python "service" with 8 pinned (`==`) packages. |

The two directories are scanned as two services, as Graveyard treats a monorepo.

Do not `npm install` or `pip install` here. Several pinned versions are deprecated on purpose, and one Python package
(`typed-ast`) does not build on current Python versions.

The source of truth for this content is `demo/haunted-house/` in the Graveyard repository. `EXPECTED.md` lists the
evaluation-set label of each direct dependency; it is for checking a scan by hand, not for tuning the model.
