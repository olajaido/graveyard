# Moved-repository probe (MV2-SRC-2)

Verdict: **FAILS**

- Confirmed-moved subjects measured: 7 (at least 2 needed)
- Capture-path `as_of`: 2026-11-03
- Failing sources: scorecard
- Failing signals: s4, s8

Only the capture path decides. The library path is informational.
S4 and S8 come from the deps.dev project document, else the Scorecard API; both are
reported as source `scorecard`. The other signals come from `github`.

## Subjects

| old name | current name | repository id | confirmed moved | measured |
|---|---|---|---|---|
| visionmedia/debug | debug-js/debug | 2871998 | yes | yes |
| mishoo/UglifyJS2 | mishoo/UglifyJS | 5569059 | yes | yes |
| substack/node-browserify | browserify/browserify | 931039 | yes | yes |
| visionmedia/express | expressjs/express | 237159 | yes | yes |
| fezvrasta/popper.js | floating-ui/floating-ui | 54994103 | yes | yes |
| jadejs/jade | pugjs/pug | 734934 | yes | yes |
| npm/inflight | isaacs/inflight-DEPRECATED-DO-NOT-USE | 19442260 | yes | yes |

## Capture path

### visionmedia/debug

| signal | old name | current name | result |
|---|---|---|---|
| s3 | 2026-10-14 | 2026-10-14 | same |
| s4 | 0 | 0 | same |
| s5 | 3 | 3 | same |
| s6_open | 60 | 60 | same |
| s6_closed | 612 | 612 | same |
| s8 | 2.6 | 2.6 | same |
| archived | False | False | same |

### mishoo/UglifyJS2

| signal | old name | current name | result |
|---|---|---|---|
| s3 | 2024-11-22 | 2024-11-22 | same |
| s4 | 0 | 0 | same |
| s5 | 0 | 0 | same |
| s6_open | 33 | 33 | same |
| s6_closed | 2894 | 2894 | same |
| s8 | 2.7 | 2.7 | same |
| archived | False | False | same |

### substack/node-browserify

| signal | old name | current name | result |
|---|---|---|---|
| s3 | 2026-10-24 | 2026-10-24 | same |
| s4 | 0 | 0 | same |
| s5 | 2 | 2 | same |
| s6_open | 350 | 350 | same |
| s6_closed | 1177 | 1177 | same |
| s8 | 3.9 | 3.9 | same |
| archived | False | False | same |

### visionmedia/express

| signal | old name | current name | result |
|---|---|---|---|
| s3 | 2026-11-02 | 2026-11-02 | same |
| s4 | 10 | 10 | same |
| s5 | 44 | 44 | same |
| s6_open | 113 | 113 | same |
| s6_closed | 3973 | 3973 | same |
| s8 | 8.5 | 8.5 | same |
| archived | False | False | same |

### fezvrasta/popper.js

| signal | old name | current name | result |
|---|---|---|---|
| s3 | 2026-11-12 | 2026-11-12 | same |
| s4 | 10 | missing | missing |
| s5 | 24 | 24 | same |
| s6_open | 40 | 40 | same |
| s6_closed | 1456 | 1456 | same |
| s8 | 4.7 | missing | missing |
| archived | False | False | same |

### jadejs/jade

| signal | old name | current name | result |
|---|---|---|---|
| s3 | 2026-03-13 | 2026-03-13 | same |
| s4 | 0 | 0 | same |
| s5 | 1 | 1 | same |
| s6_open | 300 | 300 | same |
| s6_closed | 2289 | 2289 | same |
| s8 | 3.9 | 3.9 | same |
| archived | False | False | same |

### npm/inflight

| signal | old name | current name | result |
|---|---|---|---|
| s3 | 2024-05-23 | 2024-05-23 | same |
| s4 | 0 | missing | missing |
| s5 | 0 | 0 | same |
| s6_open | 0 | 0 | same |
| s6_closed | 6 | 6 | same |
| s8 | 2.9 | missing | missing |
| archived | True | True | same |

## Failures

| subject | source | signal |
|---|---|---|
| fezvrasta/popper.js | scorecard | s4 |
| fezvrasta/popper.js | scorecard | s8 |
| npm/inflight | scorecard | s4 |
| npm/inflight | scorecard | s8 |
