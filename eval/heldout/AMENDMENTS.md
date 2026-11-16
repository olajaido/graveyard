# Harness amendments

Append-only. An entry lists harness files (those in `FROZEN_HARNESS.json`) that change after the `mortality-v2-frozen` tag. The entry is committed before the change commit, and its date is not after the date of that change. Model files, the manifest, `weights.v2.yaml`, the source changes and the held-out configuration (`dataset.yaml`, `gate.yaml`, `f/queries.tsv`) cannot be amended; a change to them is a new model version.

Entry format (not a real entry):

```
## YYYY-MM-DD <name>
paths: <comma-separated harness paths>
reason: <one paragraph: what was wrong, what the change does, why it does not depend on any held-out result>
```

## Entries

None.
