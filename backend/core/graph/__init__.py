"""Dependency graph, scope inputs and exposure inputs for a scan.

Purpose: turn one or more CycloneDX BOMs (one per manifest directory) into a
single graph of packages, together with the exposure inputs the scoring
pipeline needs (``PathInfo`` sets and ``services_affected`` per package).
This package is pure: no I/O, no logging, no clock, no randomness.

D1, identity: a node is identified by ``package_key`` (``core.purl``), never
by ``bom-ref`` or by the full purl. The ``bom-ref`` of a Syft component carries
a ``?package-id=`` hash and is lower-case for npm, while the purl keeps the
registry spelling; only ``package_key`` agrees across both and across SBOM
producers.

D4/D5, path semantics: ``PathInfo.runtime`` is the scope of the first hop, the
direct dependency a path starts from. Paths are simple paths (no repeated
node). They are decided without enumerating paths: the search keeps at most
two origin labels per node, so a self-cyclic direct dependency is still
direct, and a node that is reachable from its own cycle only is not
transitive.

D14, warnings: ``GraphWarning`` is the only diagnostics channel. Nothing in
this package prints, logs or raises for recoverable input problems; it records
a warning with a code from ``WARNING_CODES`` instead.

The public API is added in later tasks.
"""
