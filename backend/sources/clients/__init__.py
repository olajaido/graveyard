"""Per-source async clients for the autopsy source clients.

Purpose: one module per external source (deps.dev, OSV, npm registry, PyPI,
npm downloads, pypistats, Scorecard API, GitHub GraphQL). Each client builds
requests with the URL builders in ``core.sources``, sends them through the
gateway and returns the parsed result from ``core.sources.parse``.

D3: a client returns an outcome value (``Ok``, ``NotFound`` or ``Failed``) and
never raises for source, network or data problems. D4: a 404 is a definitive
absence, a failure is a warning and failures are not cached. D11: response
bodies are never copied into evidence, notes or warnings.

Clients import ``core.sources``, never ``core.scoring``.
"""
