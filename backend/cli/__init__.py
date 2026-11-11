"""The graveyard command line: `graveyard autopsy`.

Purpose: run the autopsy pipeline from a terminal or CI job and print a table
and a versioned JSON report, with `--fail-on` exit codes.

Input (D1): two modes. Project mode takes a PATH (optionally with --sbom);
single-package mode takes one or more --purl values.

Environment (D7): the process environment is read only in `__main__.py`.
Every other module receives what it needs as arguments.

No model logic (D9): this package holds no scoring rules. Scoring is
`core.scoring`; the CLI only calls it and formats the results.

No network of its own (D17): all network access goes through `sources`.
The CLI opens no sockets and imports no HTTP client.
"""
