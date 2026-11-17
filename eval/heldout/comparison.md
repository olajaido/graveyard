# Held-out comparison: v1 to v2

- labels_sha256: `874153636f3eb60a459d352efdf5010011e47bfe970e9be6e46a359186ce05a4`
- fixture_set_sha256: `87f7cd6847241cb721ea33c86cb90036e681cdbed18a42fa3eee77d31e5d84a0`
- as_of: `2026-11-17`
- rows: 18, changed class: 7

Descriptive only (MV2-GATE-7); not a model run and not a gate input.

## Label: dead

| v1 predicted | v2 predicted | rows |
|---|---|---|
| dead | dead | 10 |
| dead | ailing | 3 |
| alive | alive | 1 |

## Label: finished-healthy

| v1 predicted | v2 predicted | rows |
|---|---|---|
| dead | ailing | 1 |

## Label: alive

| v1 predicted | v2 predicted | rows |
|---|---|---|
| none | none | 0 |

## Label: ailing

| v1 predicted | v2 predicted | rows |
|---|---|---|
| dead | ailing | 3 |
