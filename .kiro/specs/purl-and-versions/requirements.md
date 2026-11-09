# Spec: purl-and-versions

> **Source of truth:** PRD EX-4, EX-7, EX-9 and §11.6 (v1.4), `docs/adr/0001-data-sources-and-sbom.md` (decision 7), `docs/SPIKES.md` (Q4: `SOURCE_REPO` formats vary).
> **Scope:** pure logic in `backend/core/purl/`:
> 1. a thin wrapper over `packageurl-python` that parses, formats and normalises npm and PyPI purls, and derives a dedupe key and a registry name from them;
> 2. a GitHub repository-URL normaliser that maps every supported URL form to `github.com/<owner>/<repo>` or `None`, plus a case-insensitive repo key.
>
> **Out of scope:** semver / PEP 440 parsing, ordering and range matching (D1); version normalisation (D2); fetching repository URLs from deps.dev, npm or PyPI (that belongs to `backend/sources/`); the dependency graph builder; any network I/O.

---

## Design decisions recorded by this spec

| ID | Decision | Rationale and consequence |
|----|----------|---------------------------|
| D1 | **No in-house semver or PEP 440 range matching.** | OSV `/v1/querybatch` matches the resolved version against affected ranges server-side and returns only the advisories that affect it. Our own matcher would duplicate OSV and add a large, bug-prone surface. The "Semver/PEP 440 range matching" row has been removed from PRD §11.6 and from `.kiro/steering/testing.md` "Required Properties", with a note pointing here. |
| D2 | **Versions are preserved verbatim.** | The core does not normalise `1.0` to `1.0.0` or `1.0.0a1` to `1.0.0-alpha.1`. Syft emits lockfile versions as written, so purls from one scan are consistent. EX-7 dedupe is therefore exact-string on the version. |
| D3 | **npm names and scopes keep their case.** | Legacy npm packages have upper-case names (e.g. `JSONStream`), and the npm registry and OSV are case-sensitive. `packageurl-python` 0.17.6 lower-cases npm names when parsing *and* formatting (it follows the purl-spec npm rule), so the wrapper must not use the library's `to_string()` for npm names. See the design. |
| D4 | **Grammar is delegated to `packageurl-python`.** | The library splits the string, decodes components, and canonicalises qualifiers and subpath. Our code adds: the ecosystem allow-list, npm case preservation, PEP 503 names, the stricter checks in PV-PURL-11, the length cap, and conversion of every failure into `ValueError`. |
| D5 | **The repo normaliser never decodes, follows or fetches.** | It is a pure string function. It rejects anything ambiguous instead of guessing, so a crafted URL can never resolve to a GitHub repo it does not literally name (threat T2). |
| D6 | **Display form and key form are separate.** | `normalise_repo_url` keeps the owner's and repo's case for display and links. `repo_key` lower-cases them for dedupe and caching, because GitHub owner and repo names are case-insensitive. `package_key` drops qualifiers and subpath so that one package version has one cache entry, and it lower-cases npm namespace and name (D7). `format_purl` and `registry_name` keep the original case (D3). |
| D7 | **`package_key` lower-cases npm names; nothing else does.** | A spec-strict SBOM generator emits `pkg:npm/jsonstream@…` where Syft may emit `pkg:npm/JSONStream@…`; without folding, EX-7 dedupe and the AU-5 cache would treat them as two packages. npm does not allow a new package whose name differs only in case from an existing one, so folding is collision-free for the registry (this requirement relies on that npm rule). Folding is ASCII-only (`A–Z` → `a–z`): npm names are URL-safe ASCII, and Unicode case mapping could merge unrelated names (e.g. U+212A KELVIN SIGN lower-cases to `k`). PyPI names are already PEP 503-normalised, so the PyPI key is unchanged. |

### Review decisions (round 1)

1. The extra repo forms (`http://`, `git+ssh://`, `ssh://git@…`, `www.github.com`, scheme-less `github.com/<o>/<r>`) are kept. Bare `owner/repo` stays excluded: `npm publish` expands that shorthand, so it does not appear in registry metadata.
2. Qualifiers and subpath are kept in canonical form. `package_key` is added for dedupe (EX-7) and the autopsy cache (AU-5).
3. The 2,048-character cap is accepted.
4. PRD §11.6 and `testing.md` have been updated (D1).
5. `registry_name` and `repo_key` are added.
6. Example tests now use real inputs from the spikes and anchor capture.

### Review decisions (round 2)

1. `package_key` lower-cases npm namespace and name, ASCII-only (D7). `format_purl` and `registry_name` keep the original case. New property: `package_key` is case-insensitive for npm and unchanged for PyPI (PV-INV-14).
2. A task adds `JSONStream` to the npm spike fixture, runs the pinned Syft, and records the emitted purl in `docs/SPIKES.md`. The contract tests assert whatever Syft actually emits (PV-SYFT-1 to 3).
3. `git@www.github.com:…` stays rejected.

---

## Dependency

| ID | Requirement |
|----|-------------|
| PV-DEP-1 | **THE SYSTEM SHALL** add `packageurl-python` as a runtime dependency with `uv add` (run from `backend/`), exact-pinned with `==` in `[project].dependencies`, with `uv.lock` updated in the same change. The pin SHALL be the latest release at implementation time (0.17.6 when this spec was written; the probes behind the design used 0.17.6). |
| PV-DEP-2 | **THE SYSTEM SHALL** pass `uv run mypy --strict core` without `type: ignore` on `packageurl` imports. The package ships `py.typed`. |
| PV-DEP-3 | **THE SYSTEM SHALL NOT** add any other runtime dependency for this spec. |

---

## Data model

```python
Ecosystem = Literal["npm", "pypi"]

@dataclass(frozen=True)
class Purl:
    ecosystem: Ecosystem
    namespace: str | None          # npm: "@scope" or None; pypi: always None (decoded)
    name: str                      # npm: case preserved; pypi: PEP 503-normalised (decoded)
    version: str | None            # verbatim, decoded (D2); None when the purl has no version
    qualifiers: tuple[tuple[str, str], ...]   # canonical: keys lower-case, sorted, unique; no empty values (decoded)
    subpath: str | None            # canonical: no empty, "." or ".." segments (decoded)
    # __post_init__ raises ValueError if any field is invalid or non-canonical (PV-PURL-9)
```

Public functions (re-exported from `core.purl`):

```python
def parse_purl(s: str) -> Purl: ...
def format_purl(p: Purl) -> str: ...
def normalise_purl(s: str) -> str: ...
def normalise_pypi_name(name: str) -> str: ...
def package_key(p: Purl) -> str: ...
def registry_name(p: Purl) -> str: ...
def normalise_repo_url(raw: str) -> str | None: ...
def repo_key(repo: str) -> str: ...
```

---

## Purl parsing, formatting and normalisation

| ID | Requirement |
|----|-------------|
| PV-PURL-1 | **THE SYSTEM SHALL** provide `parse_purl(s)`, which parses `s` with `packageurl-python` and returns a canonical `Purl`. |
| PV-PURL-2 | **IF** the purl type, compared case-insensitively, is not `npm` or `pypi` **THEN** `parse_purl` SHALL raise `ValueError` naming the unsupported type (e.g. `maven`, `github`, `golang`). The scheme SHALL be `pkg:` (lower-case, as the library requires); `pkg://` is accepted as the purl spec allows. |
| PV-PURL-3 | **WHEN** the type is `npm` **THE SYSTEM SHALL** accept a namespace that is absent or that is `@` followed by a non-empty scope, whether written `@scope` or `%40scope` in the input. **IF** the namespace is present and does not start with `@`, or the scope is empty or contains `@` or `/`, or the name is empty **THEN** `parse_purl` SHALL raise `ValueError`. This covers `pkg:npm/@scope` with no name, which the library also rejects. |
| PV-PURL-4 | **WHEN** the type is `npm` **THE SYSTEM SHALL** preserve the case of the namespace and name (D3). |
| PV-PURL-5 | **WHEN** the type is `pypi` **THE SYSTEM SHALL** set `name = normalise_pypi_name(name)`, where `normalise_pypi_name(n) = re.sub(r"[-_.]+", "-", n).lower()` (PEP 503). The library's own normalisation is weaker: it maps `_` to `-` but leaves `.` and does not collapse runs, so `zope.interface` stays as-is and `a__b` becomes `a--b`. **IF** a `pypi` purl has a namespace **THEN** `parse_purl` SHALL raise `ValueError`. |
| PV-PURL-6 | **THE SYSTEM SHALL** decode percent-encoded components when parsing. When formatting, it SHALL encode each component with the library's `quote` function. That leaves `/` and `:` unencoded and encodes everything else outside the unreserved set; an npm scope is therefore written `%40scope`, e.g. `pkg:npm/%40babel/core@7.24.0`. |
| PV-PURL-7 | **THE SYSTEM SHALL** treat the version as optional and preserve it verbatim after decoding (D2). **IF** the `@` version separator is present but the version is empty (e.g. `pkg:npm/left-pad@`) **THEN** `parse_purl` SHALL raise `ValueError`. The library silently treats this as "no version". |
| PV-PURL-8 | **THE SYSTEM SHALL** preserve qualifiers and subpath in canonical form, as the library produces it: qualifier keys stripped, lower-cased and sorted; empty or whitespace-only values dropped; empty, `.` and `..` subpath segments dropped. **IF** a qualifier key appears more than once **THEN** `parse_purl` SHALL raise `ValueError`. The library silently keeps the last value. |
| PV-PURL-9 | **THE SYSTEM SHALL** validate `Purl` in `__post_init__` and raise `ValueError` for any field that breaks PV-PURL-2 to PV-PURL-8 or PV-PURL-11, for a `pypi` name not equal to `normalise_pypi_name(name)`, or for qualifiers that are not canonical. Every `Purl` value is therefore canonical. |
| PV-PURL-10 | **THE SYSTEM SHALL** provide `format_purl(p)`, which returns the canonical purl string for `p`, and `normalise_purl(s)`, which returns the canonical purl string for the purl denoted by `s`. |
| PV-PURL-11 | **THE SYSTEM SHALL** raise `ValueError` for input that the library accepts but that would not round-trip or is ambiguous: <br>• any raw whitespace or ASCII control character in `s` (the library silently strips spaces around segments); <br>• a `%` not followed by two hex digits (the library keeps it literally); <br>• a decoded npm or pypi name containing `/` (the library decodes `x%2Fy` to `x/y`, which formats as namespace `x`, name `y`); <br>• a decoded npm name containing `@`, or a pypi name that does not match the PEP 508 name pattern `^([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9])$`; <br>• a decoded namespace, name or version containing whitespace or control characters; <br>• a decoded qualifier value or subpath segment with leading or trailing whitespace (the library strips or drops these inconsistently). |
| PV-PURL-12 | **IF** `s` is longer than 2,048 characters **THEN** `parse_purl` and `normalise_purl` SHALL raise `ValueError` without invoking `packageurl-python`. (Purls arrive through `GET /packages/{purl}/autopsy`, which is untrusted input.) |
| PV-PURL-13 | **THE SYSTEM SHALL** raise only `ValueError` from `parse_purl` and `normalise_purl` for any `str` input. Any other exception raised inside the wrapper or the library SHALL be caught and re-raised as `ValueError` with the original chained (`raise … from exc`). |

---

## Package key and registry name

| ID | Requirement |
|----|-------------|
| PV-KEY-1 | **THE SYSTEM SHALL** provide `package_key(p)`, which returns `"<type>/<namespace>/<name>@<version>"`, with every component encoded as in PV-PURL-6. The `<namespace>/` segment is omitted when the namespace is `None`, and `@<version>` is omitted when the version is `None`. Equivalently, it is `format_purl(k)` with the `pkg:` prefix dropped, where `k` is `p` with qualifiers and subpath removed and, for npm, namespace and name ASCII-lower-cased (PV-KEY-4). The version is never case-folded (D2). Examples: `npm/%40babel/core@7.24.0`, `npm/jsonstream@1.3.5` (from `JSONStream`), `pypi/flask-sqlalchemy@3.1.1`. |
| PV-KEY-2 | **THE SYSTEM SHALL** document `package_key` (in its docstring and in the module docstring) as the key for EX-7 dedupe and the AU-5 autopsy cache. Callers SHALL NOT use the full purl string for these purposes, and SHALL NOT use the key where the registry name is needed (use `registry_name`). |
| PV-KEY-3 | **THE SYSTEM SHALL** make `package_key` reversible up to case: `parse_purl("pkg:" + package_key(p))` equals the key-folded `k` of PV-KEY-1 (that is, `p` with qualifiers and subpath removed, and for npm the namespace and name ASCII-lower-cased). Two packages whose names differ in more than ASCII case therefore never share a key. |
| PV-KEY-4 | **WHEN** the ecosystem is `npm` **THE SYSTEM SHALL** ASCII-lower-case the namespace and name inside `package_key` (so `JSONStream` and `jsonstream` give the same key, as do `@Babel/Core` and `@babel/core`). **WHEN** the ecosystem is `pypi` **THE SYSTEM SHALL** leave the name unchanged, because it is already PEP 503-normalised. `format_purl` and `registry_name` SHALL NOT fold case. |
| PV-REG-1 | **THE SYSTEM SHALL** provide `registry_name(p)`, which returns the decoded name that registries and APIs expect: `"@scope/name"` for scoped npm packages, `name` for unscoped npm packages (case preserved), and the PEP 503 name for PyPI. |
| PV-REG-2 | `registry_name` **SHALL NOT** percent-encode its output. Clients in `backend/sources/` encode it as each API requires (e.g. `%40scope%2Fname` for deps.dev). |

---

## GitHub repository-URL normaliser (EX-9)

`normalise_repo_url(raw)` returns `"github.com/<owner>/<repo>"` or `None`. It never raises and never returns a host other than `github.com`.

### Accepted forms

`<o>` is the owner and `<r>` is the repo. Each form may carry any of the suffixes in PV-REPO-3.

| Form | Example |
|------|---------|
| `https://github.com/<o>/<r>` | `https://github.com/psf/requests` |
| `http://github.com/<o>/<r>` | `http://github.com/psf/requests` |
| `git+https://github.com/<o>/<r>` | `git+https://github.com/request/request.git` |
| `git://github.com/<o>/<r>` | `git://github.com/broofa/node-uuid.git` |
| `git+ssh://git@github.com/<o>/<r>` | `git+ssh://git@github.com/moment/moment.git` |
| `ssh://git@github.com/<o>/<r>` | `ssh://git@github.com/moment/moment.git` |
| `git@github.com:<o>/<r>` (scp-like SSH) | `git@github.com:stevemao/left-pad.git` |
| `github:<o>/<r>` (npm shorthand) | `github:broofa/node-uuid` |
| `github.com/<o>/<r>` (scheme-less: the deps.dev project id form, and required so the output is a fixed point) | `github.com/request/request` |

`www.github.com` is accepted as the host in the URL forms and maps to `github.com`.

### Requirements

| ID | Requirement |
|----|-------------|
| PV-REPO-1 | **THE SYSTEM SHALL** provide `normalise_repo_url(raw: str) -> str \| None`, a pure function with no I/O. |
| PV-REPO-2 | **WHEN** `raw` matches an accepted form **THE SYSTEM SHALL** return `"github.com/" + owner + "/" + repo`, taking owner and repo as the first two path segments after the host (or after `github:`). |
| PV-REPO-3 | **THE SYSTEM SHALL** ignore, after the owner and repo: a fragment (`#readme`, `#v1.2.0`), a query string (`?tab=readme`), trailing slashes, and any further path segments (`/tree/main/packages/x`, `/blob/…`, `/issues`). |
| PV-REPO-4 | **THE SYSTEM SHALL** strip trailing `.git` from the repo segment repeatedly, so `r.git.git` becomes `r`. Stripping repeatedly keeps the function idempotent. |
| PV-REPO-5 | **THE SYSTEM SHALL** lower-case only the host, for comparison with `github.com` / `www.github.com`. Owner and repo SHALL keep their original case. The scheme and the `github:` prefix SHALL be matched case-insensitively. |
| PV-REPO-6 | **THE SYSTEM SHALL** strip leading and trailing ASCII whitespace from `raw` before parsing. |
| PV-REPO-7 | **THE SYSTEM SHALL** return `None` when the host, after lower-casing, is not exactly `github.com` or `www.github.com`. This includes `github.com.evil.com`, `evil.com`, `evilgithub.com`, `github.com.` (trailing dot), `gist.github.com`, `raw.githubusercontent.com`, `gitlab.com`, `bitbucket.org`, IP addresses and look-alike Unicode hosts. |
| PV-REPO-8 | **THE SYSTEM SHALL** return `None` when the input contains userinfo other than exactly `git`, or when the authority includes an explicit port. So `https://github.com@evil.com/o/r`, `https://user:token@github.com/o/r` and `https://evil.com#@github.com/o/r` all yield `None`. |
| PV-REPO-9 | **THE SYSTEM SHALL** return `None` when the owner or repo, after PV-REPO-4, is empty, is `.` or `..`, or contains a character outside `[A-Za-z0-9_.-]`. |
| PV-REPO-10 | **THE SYSTEM SHALL** return `None` when the input contains, anywhere: a backslash; an internal whitespace or ASCII control character; a `.` or `..` path segment; or a percent-encoded `.`, `/` or `\` (`%2e`, `%2f`, `%5c`, any case). |
| PV-REPO-11 | **THE SYSTEM SHALL** return `None` for any other unrecognised form. This includes bare `owner/repo`, other npm shorthands (`gitlab:`, `bitbucket:`, `gist:`), `file:` and `ftp:` URLs, non-repository URLs (e.g. documentation sites from PyPI `project_urls`), the empty string, and inputs longer than 2,048 characters. |
| PV-REPO-12 | **THE SYSTEM SHALL NOT** raise any exception for any `str` input. |
| PV-RKEY-1 | **THE SYSTEM SHALL** provide `repo_key(repo)`, which returns `repo.lower()` for any `repo` that fully matches `^github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$` (the normaliser's output shape). It is the key for dedupe and caching of repo-level signals. |
| PV-RKEY-2 | **IF** `repo` does not match that pattern **THEN** `repo_key` SHALL raise `ValueError`. It does not accept raw URLs; callers normalise first. |

---

## Example-based tests

### Purl examples (pytest, non-property)

| Input | `normalise_purl` | `package_key` | `registry_name` |
|-------|------------------|---------------|-----------------|
| `pkg:npm/%40babel/core@7.24.0` | `pkg:npm/%40babel/core@7.24.0` | `npm/%40babel/core@7.24.0` | `@babel/core` |
| `pkg:npm/@babel/core@7.24.0` | `pkg:npm/%40babel/core@7.24.0` | `npm/%40babel/core@7.24.0` | `@babel/core` |
| `pkg:NPM/left-pad@1.3.0` | `pkg:npm/left-pad@1.3.0` | `npm/left-pad@1.3.0` | `left-pad` |
| `pkg:npm/JSONStream@1.3.5` | `pkg:npm/JSONStream@1.3.5` | `npm/jsonstream@1.3.5` | `JSONStream` |
| `pkg:npm/jsonstream@1.3.5` | `pkg:npm/jsonstream@1.3.5` | `npm/jsonstream@1.3.5` | `jsonstream` |
| `pkg:npm/%40Babel/Core@7.24.0` | `pkg:npm/%40Babel/Core@7.24.0` | `npm/%40babel/core@7.24.0` | `@Babel/Core` |
| `pkg:npm/request@2.88.2?arch=x64#lib` | `pkg:npm/request@2.88.2?arch=x64#lib` | `npm/request@2.88.2` | `request` |
| `pkg:pypi/requests@2.31.0` | `pkg:pypi/requests@2.31.0` | `pypi/requests@2.31.0` | `requests` |
| `pkg:pypi/Flask_SQLAlchemy@3.1.1` | `pkg:pypi/flask-sqlalchemy@3.1.1` | `pypi/flask-sqlalchemy@3.1.1` | `flask-sqlalchemy` |
| `pkg:pypi/zope.interface@6.0` | `pkg:pypi/zope-interface@6.0` | `pypi/zope-interface@6.0` | `zope-interface` |
| `pkg:pypi/requests` | `pkg:pypi/requests` | `pypi/requests` | `requests` |
| `pkg://npm/left-pad@1.3.0` | `pkg:npm/left-pad@1.3.0` | `npm/left-pad@1.3.0` | `left-pad` |

Each of these inputs SHALL raise `ValueError`: `pkg:maven/org.apache/commons@1.0`, `pkg:github/psf/requests`, `pkg:pypi/acme/requests@1.0`, `pkg:npm/scope/name@1.0`, `pkg:npm/@scope`, `pkg:npm/left-pad@`, `pkg:npm/x%2Fy@1`, `pkg:npm/x@@1`, `pkg:npm/%zz@1`, `pkg:npm/ x @1`, `pkg:npm/x?a=1&a=2`, `PKG:npm/x@1`, `npm/left-pad@1.3.0`, and `""`.

### Syft verification (npm purl case)

| ID | Requirement |
|----|-------------|
| PV-SYFT-1 | **THE SYSTEM SHALL** add `JSONStream` (an upper-case npm name) to the npm spike fixture (`spikes/fixtures/npm`), regenerate its lockfile with scripts disabled (`npm install --package-lock-only --ignore-scripts`; nothing is executed), run the pinned Syft v1.56.0 on it with `-o cyclonedx-json`, and record the exact purl Syft emits for `JSONStream` in `docs/SPIKES.md`, with the Syft version and the command. |
| PV-SYFT-2 | **THE SYSTEM SHALL** commit the CycloneDX component (or a minimal excerpt with its `purl` and `bom-ref`) as `backend/core/purl/tests/fixtures/syft_jsonstream.json`, so tests read it without Syft or network. |
| PV-SYFT-3 | **THE SYSTEM SHALL** assert in the contract tests whatever Syft actually emitted: `parse_purl` accepts it, `registry_name` returns `JSONStream`, `package_key` equals `npm/jsonstream@<version>`, and `package_key` equals the key of the lower-case spelling `pkg:npm/jsonstream@<version>`. If Syft emits lower case, the assertions still hold and the test additionally records that fact in its name or docstring. |

### Repo examples: real inputs (pytest, non-property)

These are stored in `backend/core/purl/tests/fixtures/real_repo_urls.json`, each entry with `input`, `expected` and `source`. The expected values agree with the `repo` field of the matching anchor fixtures in `core/scoring/tests/fixtures/anchors/`.

| Input | Expected | Source |
|-------|----------|--------|
| `git+https://github.com/request/request.git` | `github.com/request/request` | npm registry `repository.url` for `request` |
| `github:broofa/node-uuid` | `github.com/broofa/node-uuid` | npm `repository` shorthand for `node-uuid` |
| `https://github.com/benjaminp/six` | `github.com/benjaminp/six` | PyPI `project_urls` for `six` (`spikes/out_pypi.json`) |
| `https://github.com/psf/requests` | `github.com/psf/requests` | PyPI `project_urls` for `requests` (`spikes/out_pypi.json`) |
| `https://requests.readthedocs.io` | `None` | PyPI `project_urls` for `requests`: a docs URL in the same list |
| `github.com/request/request` | `github.com/request/request` | deps.dev `SOURCE_REPO` `projectKey.id` for `npm:request` (`spikes/out_depsdev.json`) |

### Repo examples: synthetic (pytest, non-property)

| Input | `normalise_repo_url` | `repo_key` of result |
|-------|----------------------|----------------------|
| `git://github.com/broofa/node-uuid.git` | `github.com/broofa/node-uuid` | `github.com/broofa/node-uuid` |
| `git@github.com:stevemao/left-pad.git` | `github.com/stevemao/left-pad` | `github.com/stevemao/left-pad` |
| `https://github.com/psf/requests/tree/main/src#readme` | `github.com/psf/requests` | `github.com/psf/requests` |
| `https://GitHub.com/PyCQA/Flake8?tab=readme` | `github.com/PyCQA/Flake8` | `github.com/pycqa/flake8` |
| `  https://github.com/o/r/  ` | `github.com/o/r` | `github.com/o/r` |
| `https://github.com.evil.com/o/r` | `None` | n/a |
| `https://github.com@evil.com/o/r` | `None` | n/a |
| `https://evil.com/github.com/o/r` | `None` | n/a |
| `https://github.com/o/../evil/r` | `None` | n/a |
| `https://github.com/o/%2e%2e/r` | `None` | n/a |
| `https://github.com\@evil.com/o/r` | `None` | n/a |
| `https://github.com:8443/o/r` | `None` | n/a |
| `https://gitlab.com/o/r` | `None` | n/a |
| `https://github.com/o` | `None` | n/a |
| `o/r` | `None` | n/a |

`repo_key("https://github.com/o/r")` and `repo_key("github.com/o")` SHALL raise `ValueError`.

---

## Invariants: property-based test requirements

Each invariant is verified by Hypothesis tests tagged `@pytest.mark.property` and run under the existing profiles (`dev` = 200 examples, `ci` = 500, selected by `HYPOTHESIS_PROFILE`). Shared strategies live in `backend/core/purl/tests/strategies.py`.

### PV-INV-1: Purl round-trip

**Requirement:** For every valid-grammar npm or pypi purl string `s`, `format_purl(parse_purl(s)) == normalise_purl(s)`. For every valid `Purl` value `p`, `parse_purl(format_purl(p)) == p`.

**Acceptance criteria (Hypothesis):**
- Strategy `purls()`: generate valid `Purl` values. Npm scopes and names, versions, qualifier values and subpath segments include characters that need percent-encoding (`?`, `#`, `%`, `+`, non-ASCII; `@` in versions and qualifier values; interior spaces in qualifier values and subpath segments only), and mixed case. Pypi names include runs of `-`, `_` and `.` before normalisation.
- Strategy `purl_strings()`: render a generated purl in a non-canonical but valid variant: upper-case type, `pkg://`, `@scope` versus `%40scope`, unordered qualifiers, upper-case qualifier keys, percent-encoding of unreserved characters, a non-normalised pypi name. The strategy also returns the **expected canonical string**, computed independently with `urllib.parse.quote(…, safe="/:")`. This oracle stops the round-trip being true by construction.
- Properties:
  - `format_purl(parse_purl(s)) == normalise_purl(s)`;
  - `normalise_purl(s) == expected_canonical`;
  - `parse_purl(format_purl(p)) == p`.
- Test names: `test_purl_round_trip`, `test_purl_matches_oracle`, `test_purl_value_round_trip`.

### PV-INV-2: Purl normalisation is idempotent

**Requirement:** For every valid purl string `s`, `normalise_purl(normalise_purl(s)) == normalise_purl(s)`.

- Strategy: `purl_strings()`.
- Test name: `test_normalise_purl_idempotent`.

### PV-INV-3: Valid grammar never raises

**Requirement:** `parse_purl` never raises for a valid-grammar npm or pypi purl (PRD §11.6).

- Strategy: `purl_strings()`.
- Property: `parse_purl(s)` returns a `Purl`.
- Test name: `test_parse_valid_never_raises`.

### PV-INV-4: Invalid input raises `ValueError` and nothing else

**Requirement:** For any `str`, `parse_purl` either returns a `Purl` or raises `ValueError`. It never raises any other exception type.

- Strategies:
  - arbitrary `text()`, including surrogates, control characters, and strings over 2,048 characters;
  - mutations of valid purls: deleted, duplicated or swapped characters, a stray `%`, truncated percent-escapes, a removed `pkg:`, duplicated qualifier keys, an empty version after `@`, encoded `/` in the name;
  - valid purls with types outside the allow-list (`maven`, `github`, `golang`, `cargo`, random).
- Properties:
  - only `ValueError` escapes;
  - every disallowed type raises `ValueError`.
- Test names: `test_parse_only_raises_value_error`, `test_parse_rejects_other_ecosystems`.

### PV-INV-5: PEP 503 names

**Requirement:** `normalise_pypi_name` is idempotent. Two pypi names that differ only in case or in runs of `-`, `_` and `.` produce the same purl, the same `package_key` and the same `registry_name`.

- Strategy: a base name split at random points and rejoined with random separator runs and random casing.
- Test names: `test_pep503_idempotent`, `test_pep503_variants_collapse`.

### PV-INV-6: npm case is preserved

**Requirement:** For every valid npm purl, the parsed `namespace` and `name` equal the decoded input components exactly, including case, and `format_purl` reproduces that case.

- Strategy: `purls()` restricted to npm, with mixed-case scopes and names.
- Test name: `test_npm_case_preserved`.

### PV-INV-7: `package_key` invariance

**Requirement:** `package_key` is invariant to qualifier and subpath changes, idempotent under normalisation, and reversible up to npm case (PV-KEY-3).

- Strategies: `purls()`; `purl_strings()`; random qualifier and subpath sets.
- Properties:
  - `package_key(replace(p, qualifiers=q1, subpath=s1)) == package_key(replace(p, qualifiers=q2, subpath=s2))`;
  - `package_key(parse_purl(normalise_purl(s))) == package_key(parse_purl(s))`;
  - `parse_purl("pkg:" + package_key(p))` equals `p` with qualifiers and subpath removed and, for npm, namespace and name ASCII-lower-cased (the expected value is built in the test, not by calling `package_key`);
  - the key is stable under re-keying: `package_key(parse_purl("pkg:" + package_key(p))) == package_key(p)`.
- Test names: `test_package_key_ignores_qualifiers_subpath`, `test_package_key_idempotent_under_normalise`, `test_package_key_reversible`, `test_package_key_stable_under_rekey`.

### PV-INV-14: `package_key` case handling

**Requirement:** For npm, `package_key` is case-insensitive in namespace and name (ASCII), but the version stays case-sensitive. For PyPI, `package_key` equals the PEP 503 form and is unchanged by the key step. `format_purl` and `registry_name` preserve case (PV-INV-6).

- Strategy: `purls()` plus a per-character ASCII case flip applied to the npm namespace and name (non-ASCII characters are left as they are).
- Properties:
  - npm: `package_key(p) == package_key(case_flipped(p))`;
  - npm: if two purls differ only in a non-ASCII character's case, or only in the version's case, their keys differ;
  - npm: `registry_name(p)` and `format_purl(p)` of `case_flipped(p)` differ from those of `p` whenever the flip changed a character (case is not lost);
  - pypi: `package_key(p).split("/", 1)[1].split("@", 1)[0] == p.name` (the name is untouched; it is already normalised);
  - the folded key is ASCII-lower in its npm name and namespace parts after percent-decoding.
- Test names: `test_package_key_npm_case_insensitive`, `test_package_key_npm_version_and_non_ascii_not_folded`, `test_package_key_keeps_case_in_other_outputs`, `test_package_key_pypi_unchanged`.

### PV-INV-8: `registry_name` stability

**Requirement:** `registry_name(parse_purl(format_purl(p))) == registry_name(p)` for every valid `Purl`. For npm, the result starts with `@` and contains exactly one `/` if and only if `p.namespace` is not `None`.

- Strategy: `purls()`.
- Test names: `test_registry_name_round_trip`, `test_registry_name_npm_shape`.

### PV-INV-9: Repo normaliser is idempotent

**Requirement:** For every `str` `s`, if `r = normalise_repo_url(s)` is not `None` then `normalise_repo_url(r) == r`.

- Strategies: `repo_urls()` (PV-INV-12) plus arbitrary `text()`.
- Test name: `test_repo_normaliser_idempotent`.

### PV-INV-10: Repo normaliser output shape

**Requirement:** For every `str` `s`, `normalise_repo_url(s)` is `None` or fully matches `^github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`, and the function never raises (PV-REPO-12).

- Strategies: `repo_urls()`, `adversarial_repo_urls()` and arbitrary `text()`.
- Properties:
  - the output is `None` or matches the pattern with `re.fullmatch`;
  - neither segment is `.` or `..`;
  - no exception escapes.
- Test names: `test_repo_output_shape`, `test_repo_never_raises`.

### PV-INV-11: Adversarial inputs never yield a GitHub result

**Requirement:** No input whose real host is not `github.com` / `www.github.com`, or that uses userinfo tricks or path traversal, yields a non-`None` result.

- Strategy `adversarial_repo_urls()`: combine each accepted scheme with:
  - **other hosts**: random domains; `github.com.<random>`; `<random>github.com`; `<random>.github.com`; `github.com.`; IPv4 and IPv6 literals; Unicode look-alikes of `github.com`;
  - **userinfo tricks**: `github.com@<evil>`, `<random>:<random>@github.com`, `<evil>#@github.com`, `<evil>?@github.com`;
  - **path traversal**: `.` and `..` segments at random positions; `%2e`, `%2f` and `%5c` in random case; backslashes;
  - an explicit port, and inserted control or whitespace characters.
- Property: `normalise_repo_url(s) is None`.
- Test name: `test_repo_adversarial_never_github`.

### PV-INV-12: Accepted forms give the exact owner and repo

**Requirement:** For any valid owner and repo, every accepted form with any combination of PV-REPO-3 and PV-REPO-4 suffixes normalises to exactly `github.com/<owner>/<repo>`, with case preserved.

- Strategy `repo_urls()`: owner and repo drawn from `[A-Za-z0-9_.-]+` (excluding `.`, `..` and names ending in `.git`), rendered in a random accepted form with random-case scheme and host, and with optional `.git`, trailing `/`, extra path segments, `?query` and `#fragment`. The strategy also returns the expected result.
- Property: `normalise_repo_url(url) == f"github.com/{owner}/{repo}"`.
- Test name: `test_repo_accepted_forms_exact`.

### PV-INV-13: `repo_key` is idempotent and case-insensitive

**Requirement:** For every normaliser output `r`, `repo_key(repo_key(r)) == repo_key(r)`. For every case variant `v` of `r`, `repo_key(v) == repo_key(r)`.

- Strategies: outputs of `repo_urls()`, each paired with a random per-character case flip.
- Properties:
  - idempotence;
  - case-insensitivity;
  - `repo_key(r)` fully matches `^github\.com/[a-z0-9_.-]+/[a-z0-9_.-]+$`;
  - two accepted-form URLs that differ only in owner or repo case have equal `repo_key` of their normalised outputs.
- Test names: `test_repo_key_idempotent`, `test_repo_key_case_insensitive`.

---

## Non-functional requirements

| ID | Requirement |
|----|-------------|
| PV-NFR-1 | **THE SYSTEM SHALL** keep `backend/core/purl/` free of I/O, clock reads and environment reads (structure steering: `core/` is pure). Tests may read their own fixtures via `Path(__file__).parent`. |
| PV-NFR-2 | **THE SYSTEM SHALL** colocate tests in `backend/core/purl/tests/` (fixtures in `tests/fixtures/`), following the `core/scoring/tests/` convention so that the existing `testpaths = ["core"]` collects them. |
| PV-NFR-3 | **THE SYSTEM SHALL** pass, from `backend/`: `uv run pytest -q`, `HYPOTHESIS_PROFILE=ci uv run pytest -m property -q`, `uv run ruff check`, `uv run ruff format --check` and `uv run mypy --strict core`. |
| PV-NFR-4 | **THE SYSTEM SHALL** reach at least 85% line coverage on `backend/core/purl/` (PRD testing table). |
| PV-NFR-5 | Each implementation task in `tasks.md` **SHALL** be paired with the unit and property tests for the requirements it implements, in the same task or an immediately following sub-task. Tests are not deferred to a final task. |
