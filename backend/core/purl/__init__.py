"""Package URL (purl) parsing, formatting and cache keys; repo-URL normalisation.

Pure, I/O-free logic. Only npm and PyPI purls are supported. Parsing and
formatting wrap ``packageurl-python``; a contract test pins the library
behaviours we compensate for, so a failing contract test after a library
upgrade is the signal to simplify the wrapper.

Purl functions
--------------
``parse_purl(s)`` turns a string into a canonical, frozen ``Purl`` and raises
``ValueError`` (and nothing else) on bad input. ``format_purl(p)`` renders the
full canonical purl string, keeping the npm name's case, qualifiers and
subpath. ``normalise_purl(s)`` is ``format_purl(parse_purl(s))``.

Which one to use for a package
------------------------------
- ``package_key(p)``: identifies a package version independent of qualifiers
  and subpath, with npm namespace and name ASCII-lower-cased. It is the key
  for EX-7 dedupe and the AU-5 autopsy cache (PV-KEY-2). Callers must not use
  the full purl string (``format_purl``) for those purposes, because
  qualifiers, subpath and npm name case would split one package into many.
- ``registry_name(p)``: the decoded name as the registry spells it
  (``@scope/name`` or ``name``), case preserved. Use it for registry and API
  lookups. Never use ``package_key`` there: it is case-folded and URL-encoded
  (``npm/jsonstream@1.3.5`` for ``JSONStream``), so it can name the wrong
  package or none.
- ``format_purl(p)``: the faithful canonical purl for display, export and
  SBOM or VEX output. It is not a dedupe key.

Repo functions
--------------
- ``normalise_repo_url(raw)``: returns the display form
  ``github.com/<owner>/<repo>`` (case preserved) or ``None`` when the input
  is not a supported GitHub repo URL. Use it to show and link the repo.
- ``repo_key(repo)``: takes that display form and returns it lower-cased. It
  is the dedupe and cache key for repo-level evidence, since GitHub treats
  owner and repo names case-insensitively. It raises ``ValueError`` for
  anything that is not normalised output. Do not display it.

``core.purl`` does not import ``core.scoring``.
"""

from core.purl.model import Ecosystem, Purl, normalise_pypi_name
from core.purl.purl import (
    format_purl,
    normalise_purl,
    package_key,
    parse_purl,
    registry_name,
)
from core.purl.repo_url import normalise_repo_url, repo_key

__all__ = [
    "Ecosystem",
    "Purl",
    "format_purl",
    "normalise_purl",
    "normalise_pypi_name",
    "normalise_repo_url",
    "package_key",
    "parse_purl",
    "registry_name",
    "repo_key",
]
