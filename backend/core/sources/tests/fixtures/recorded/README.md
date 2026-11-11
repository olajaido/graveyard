# Recorded source responses

Written by `scripts/record_source_responses.py` (spec `autopsy-sources`, T11/T12). Bodies are
stored verbatim as parsed JSON; no request header is stored. Do not edit by hand.

| File | Source | Command | httpx | Recorded on | Notes |
|---|---|---|---|---|---|
| anchors.cassette.json | deps.dev, OSV, npm, PyPI, pypistats, Scorecard, GitHub GraphQL (live) | uv run python ../scripts/record_source_responses.py --fallbacks --probe-pypistats | 0.28.1 | 2026-11-11 | 51 exchanges, nine anchors at as_of 2026-11-03, 2 retried request(s) keep the last answer |
| pypistats_probe.json | pypistats.org (live) | uv run python ../scripts/record_source_responses.py --fallbacks --probe-pypistats | 0.28.1 | 2026-11-11 | 12 requests; safe interval 0.5; stopped at 429: False |
